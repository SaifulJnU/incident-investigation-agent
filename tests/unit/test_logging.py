import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from incident_investigation_agent.core.config import Settings
from incident_investigation_agent.core.logging import (
    InvestigationFormatter,
    bind_investigation,
    in_context,
)
from incident_investigation_agent.db.models import Base, utcnow
from incident_investigation_agent.repositories.cases import open_incident, queue_run
from incident_investigation_agent.services.gather import gather
from incident_investigation_agent.services.investigation import execute, release_held_runs

_FORMAT = InvestigationFormatter("%(levelname)s %(message)s")


class _Grab(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def _lines(handler: _Grab) -> list[str]:
    return [_FORMAT.format(record) for record in handler.records]


def _listen():
    handler = _Grab()
    logger = logging.getLogger("incident_investigation_agent")
    previous = logger.level
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    return logger, previous, handler


def _silence(logger, previous, handler) -> None:
    logger.removeHandler(handler)
    logger.setLevel(previous)


def test_a_line_names_the_case_only_while_the_run_is_bound():
    logger, previous, handler = _listen()
    try:
        logging.getLogger("incident_investigation_agent.worker").info("worker ready")
        with bind_investigation("case-1", "run-1"):
            logging.getLogger("incident_investigation_agent.worker").info("investigation started")
        logging.getLogger("incident_investigation_agent.worker").info("worker ready again")
    finally:
        _silence(logger, previous, handler)

    assert _lines(handler) == [
        "INFO worker ready",
        "INFO investigation started case=case-1 run=run-1",
        "INFO worker ready again",
    ]


def test_two_runs_do_not_share_a_case_id():
    logger, previous, handler = _listen()
    barrier = threading.Barrier(2)

    def work(case_id: str, run_id: str) -> None:
        with bind_investigation(case_id, run_id):
            barrier.wait(timeout=2)
            logging.getLogger("incident_investigation_agent.worker").info("investigation started")

    try:
        threads = [
            threading.Thread(target=work, args=("case-a", "run-a")),
            threading.Thread(target=work, args=("case-b", "run-b")),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=2)
            assert thread.is_alive() is False
    finally:
        _silence(logger, previous, handler)

    assert set(_lines(handler)) == {
        "INFO investigation started case=case-a run=run-a",
        "INFO investigation started case=case-b run=run-b",
    }


def test_a_connector_thread_keeps_the_same_run():
    logger, previous, handler = _listen()

    def searched() -> None:
        logging.getLogger("incident_investigation_agent.gather").info("connector returned")

    try:
        with bind_investigation("case-1", "run-1"):
            with ThreadPoolExecutor(max_workers=1) as pool:
                pool.submit(in_context(searched)).result(timeout=2)
    finally:
        _silence(logger, previous, handler)

    assert _lines(handler) == ["INFO connector returned case=case-1 run=run-1"]


def test_search_finished_names_the_open_run():
    logger, previous, handler = _listen()
    settings = Settings(
        model_provider="ollama",
        ollama_host="http://localhost:11434",
        ollama_model="llama3.1",
        bedrock_model_id="test-model",
        aws_region="us-west-2",
        log_dir=Path("examples/logs"),
        case_dir=Path(".case"),
        database_url="sqlite+pysqlite://",
        app_env="local",
        connectors=("local_logs",),
    )
    try:
        with bind_investigation("case-1", "run-1"):
            gather(settings, "checkout-api")
    finally:
        _silence(logger, previous, handler)

    finished = [line for line in _lines(handler) if "search finished" in line]
    assert len(finished) == 1
    assert "connectors=local_logs" in finished[0]
    assert "case=case-1 run=run-1" in finished[0]
    assert "findings=" in finished[0]


def test_execute_logs_the_case_and_the_run_from_start_to_finish():
    factory = _factory()
    with factory() as session:
        incident = open_incident(
            session,
            title="Checkout errors",
            summary="500s after the deploy.",
            service="checkout-api",
            severity="sev1",
            started_at=utcnow(),
        )
        run = queue_run(session, incident, provider="ollama", model_name="llama3.1")
        incident_id = incident.id
        run_id = run.id
        session.commit()

    logger, previous, handler = _listen()
    try:
        execute(factory, _settings(), run_id, lambda *_args: "Leading cause: vault timeout.")
    finally:
        _silence(logger, previous, handler)

    text = "\n".join(_lines(handler))
    assert f"investigation started service=checkout-api provider=ollama case={incident_id} run={run_id}" in text
    assert f"investigation completed seconds=" in text
    assert f"case={incident_id} run={run_id}" in text
    assert text.count(f"case={incident_id} run={run_id}") >= 2


def test_a_failed_run_logs_the_case_and_the_run_on_the_error_line():
    factory = _factory()
    with factory() as session:
        incident = open_incident(
            session,
            title="Search timeouts",
            summary="Search started failing.",
            service="search-api",
            severity="sev2",
            started_at=utcnow(),
        )
        run = queue_run(session, incident, provider="ollama", model_name="llama3.1")
        incident_id = incident.id
        run_id = run.id
        session.commit()

    def investigate(*_args):
        raise RuntimeError("ollama is not running")

    logger, previous, handler = _listen()
    try:
        execute(factory, _settings(), run_id, investigate)
    finally:
        _silence(logger, previous, handler)

    failed = [line for line in _lines(handler) if "investigation failed" in line]
    assert len(failed) == 1
    assert failed[0].startswith("ERROR investigation failed")
    assert f"case={incident_id} run={run_id}" in failed[0]
    assert "ollama is not running" in failed[0]


def test_releasing_a_held_run_names_that_case():
    factory = _factory()
    with factory() as session:
        incident = open_incident(
            session,
            title="Checkout errors",
            summary="500s after the deploy.",
            service="checkout-api",
            severity="sev1",
            started_at=utcnow(),
        )
        run = queue_run(session, incident, provider="ollama", model_name="llama3.1")
        run.status = "running"
        incident.status = "investigating"
        incident_id = incident.id
        run_id = run.id
        session.commit()

    logger, previous, handler = _listen()
    try:
        with factory() as session:
            assert release_held_runs(session, [run_id]) == 1
            session.commit()
    finally:
        _silence(logger, previous, handler)

    assert _lines(handler) == [
        f"INFO investigation released reason=worker-stopped case={incident_id} run={run_id}"
    ]


def _factory():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _settings() -> Settings:
    return Settings(
        model_provider="ollama",
        ollama_host="http://localhost:11434",
        ollama_model="llama3.1",
        bedrock_model_id="test-model",
        aws_region="us-west-2",
        log_dir=Path("examples/logs"),
        case_dir=Path(".case"),
        database_url="sqlite+pysqlite://",
    )
