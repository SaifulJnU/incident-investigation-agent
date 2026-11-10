import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from incident_investigation_agent.db.models import Base, Incident, InvestigationRun
from incident_investigation_agent.services.metrics import investigation_metrics


def _factory():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _incident() -> Incident:
    return Incident(
        id=uuid.uuid4(),
        title="Checkout errors",
        summary="POST /checkout returns 500.",
        service="checkout-api",
        severity="sev1",
        started_at=datetime(2026, 11, 10, 11, 0, tzinfo=timezone.utc),
    )


def _run(incident_id, status: str, **times) -> InvestigationRun:
    return InvestigationRun(
        id=uuid.uuid4(),
        incident_id=incident_id,
        status=status,
        created_at=times.get("created_at", datetime(2026, 11, 10, 11, 0, tzinfo=timezone.utc)),
        finished_at=times.get("finished_at"),
    )


def test_metrics_counts_the_queue_and_the_last_hour():
    factory = _factory()
    now = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)
    with factory() as session:
        cases = [_incident() for _ in range(5)]
        session.add_all(cases)
        session.add(_run(cases[0].id, "queued", created_at=now - timedelta(seconds=90)))
        session.add(_run(cases[1].id, "running"))
        session.add(
            _run(cases[2].id, "completed", finished_at=now - timedelta(minutes=10)),
        )
        session.add(
            _run(cases[3].id, "completed", finished_at=now - timedelta(hours=2)),
        )
        session.add(
            _run(cases[4].id, "failed", finished_at=now - timedelta(minutes=5)),
        )
        session.commit()

    with factory() as session:
        body = investigation_metrics(session, now=now)

    assert body == {
        "queued": 1,
        "running": 1,
        "completed_last_hour": 1,
        "failed_last_hour": 1,
        "oldest_queued_seconds": 90,
    }
    assert "Checkout" not in str(body)


def test_an_empty_queue_has_no_oldest_age():
    factory = _factory()
    with factory() as session:
        body = investigation_metrics(session)
    assert body["queued"] == 0
    assert body["oldest_queued_seconds"] is None
