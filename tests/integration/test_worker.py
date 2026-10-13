from datetime import timedelta
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from incident_investigation_agent.core.config import Settings
from incident_investigation_agent.db.models import Base, EvidenceItem, Incident, InvestigationRun, utcnow
from incident_investigation_agent.repositories.cases import open_incident, queue_run
from incident_investigation_agent.services.investigation import (
    execute,
    release_held_runs,
    release_stale_runs,
)
from incident_investigation_agent.worker import release_on_stop
from incident_investigation_agent.services.report import message_text


def test_message_text_reads_strands_blocks():
    result = type(
        "Result",
        (),
        {"message": {"role": "assistant", "content": [{"text": "Vault timeout."}]}},
    )()
    assert message_text(result) == "Vault timeout."


def test_execute_stores_the_note_and_reopens_the_case():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
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
        run_id = run.id
        session.commit()

    def investigate(_settings, store, prompt, _service):
        assert "Checkout errors" in prompt
        store.add("hypothesis", "The card vault timed out.", "agent")
        return "Leading cause: vault timeout."

    execute(factory, _settings(), run_id, investigate)

    with factory() as session:
        finished = session.get(InvestigationRun, run_id)
        incident = session.scalars(select(Incident)).one()
        evidence = session.scalars(select(EvidenceItem)).all()
    assert finished.status == "completed"
    assert finished.report == "Leading cause: vault timeout."
    assert incident.status == "open"
    assert evidence[0].summary == "The card vault timed out."


def test_execute_records_a_failure():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
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
        run_id = run.id
        session.commit()

    def investigate(_settings, _store, _prompt, _service):
        raise RuntimeError("ollama is not running")

    execute(factory, _settings(), run_id, investigate)

    with factory() as session:
        finished = session.get(InvestigationRun, run_id)
    assert finished.status == "failed"
    assert "ollama is not running" in finished.error


def test_a_run_left_by_a_stopped_worker_can_be_investigated_again():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
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
        run.started_at = utcnow() - timedelta(minutes=30)
        incident.status = "investigating"
        session.commit()

    with factory() as session:
        released = release_stale_runs(session, older_than_minutes=20)
        session.commit()
        finished = session.scalars(select(InvestigationRun)).one()
        incident = session.scalars(select(Incident)).one()
    assert released == 1
    assert finished.status == "failed"
    assert incident.status == "open"


def test_a_deploy_releases_the_run_this_worker_holds():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        held_case = open_incident(
            session,
            title="Checkout errors",
            summary="500s after the deploy.",
            service="checkout-api",
            severity="sev1",
            started_at=utcnow(),
        )
        held = queue_run(session, held_case, provider="ollama", model_name="llama3.1")
        held.status = "running"
        held.started_at = utcnow() - timedelta(minutes=1)
        held_case.status = "investigating"
        other_case = open_incident(
            session,
            title="Payments latency",
            summary="p99 climbed.",
            service="payments-api",
            severity="sev2",
            started_at=utcnow(),
        )
        other = queue_run(session, other_case, provider="ollama", model_name="llama3.1")
        other.status = "running"
        other.started_at = utcnow() - timedelta(minutes=1)
        other_case.status = "investigating"
        held_id = held.id
        other_id = other.id
        session.commit()

    with factory() as session:
        assert release_stale_runs(session, older_than_minutes=20) == 0
        session.commit()

    released = release_on_stop(factory, [held_id])

    with factory() as session:
        held_run = session.get(InvestigationRun, held_id)
        other_run = session.get(InvestigationRun, other_id)
        cases = {item.service: item.status for item in session.scalars(select(Incident))}
    assert released == 1
    assert held_run.status == "failed"
    assert held_run.error == "The worker stopped before this run finished."
    assert cases["checkout-api"] == "open"
    assert other_run.status == "running"
    assert cases["payments-api"] == "investigating"


def test_stopping_during_the_note_does_not_put_the_run_back():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
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
        run_id = run.id
        session.commit()

    def investigate(_settings, _store, _prompt, _service):
        with factory() as session:
            release_held_runs(session, [run_id])
            session.commit()
        return "This note arrived after the worker stopped."

    execute(factory, _settings(), run_id, investigate)

    with factory() as session:
        finished = session.get(InvestigationRun, run_id)
        incident = session.scalars(select(Incident)).one()
    assert finished.status == "failed"
    assert finished.report is None
    assert finished.error == "The worker stopped before this run finished."
    assert incident.status == "open"


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
