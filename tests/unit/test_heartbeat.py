import threading
from datetime import timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from incident_investigation_agent.db.models import Base, WorkerBeat, utcnow
from incident_investigation_agent.services.heartbeat import (
    STALE_AFTER_SECONDS,
    clear_beat,
    record_beat,
    worker_alive,
)
from incident_investigation_agent.worker import run_heartbeat, silence_beat


def _factory():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def test_a_fresh_beat_is_alive_and_a_stale_one_is_not():
    factory = _factory()
    with factory() as session:
        assert worker_alive(session) is False
        record_beat(session)
        session.commit()

    with factory() as session:
        assert worker_alive(session) is True
        row = session.get(WorkerBeat, "worker")
        row.beat_at = utcnow() - timedelta(seconds=STALE_AFTER_SECONDS + 1)
        session.commit()

    with factory() as session:
        assert worker_alive(session) is False


def test_stopping_the_worker_removes_the_beat():
    factory = _factory()
    with factory() as session:
        record_beat(session)
        session.commit()

    silence_beat(factory)

    with factory() as session:
        assert session.get(WorkerBeat, "worker") is None
        assert worker_alive(session) is False


def test_clear_beat_leaves_other_rows():
    factory = _factory()
    with factory() as session:
        record_beat(session, name="worker")
        record_beat(session, name="other")
        clear_beat(session)
        session.commit()
        assert session.get(WorkerBeat, "worker") is None
        assert session.get(WorkerBeat, "other") is not None


def test_the_heartbeat_loop_writes_until_stopped():
    factory = _factory()
    stop = threading.Event()
    thread = threading.Thread(target=run_heartbeat, args=(factory, stop, 0.01))
    thread.start()
    try:
        deadline = utcnow() + timedelta(seconds=2)
        alive = False
        while utcnow() < deadline:
            with factory() as session:
                alive = worker_alive(session)
            if alive:
                break
        assert alive is True
    finally:
        stop.set()
        thread.join(timeout=2)
    assert thread.is_alive() is False
