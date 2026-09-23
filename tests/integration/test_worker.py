from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from incident_investigation_agent.core.config import Settings
from incident_investigation_agent.db.models import Base, EvidenceItem, Incident, InvestigationRun, utcnow
from incident_investigation_agent.repositories.cases import open_incident, queue_run
from incident_investigation_agent.services.investigation import execute
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

    def investigate(_settings, store, prompt):
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

    def investigate(_settings, _store, _prompt):
        raise RuntimeError("ollama is not running")

    execute(factory, _settings(), run_id, investigate)

    with factory() as session:
        finished = session.get(InvestigationRun, run_id)
    assert finished.status == "failed"
    assert "ollama is not running" in finished.error


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
