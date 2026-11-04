import os
import socket
import threading
from datetime import timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from incident_investigation_agent.db.models import Base, WorkerBeat, utcnow
from incident_investigation_agent.services.heartbeat import (
    NAME_LIMIT,
    STALE_AFTER_SECONDS,
    clear_beat,
    process_beat_name,
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
        record_beat(session, name="host-a-1")
        session.commit()

    silence_beat(factory, "host-a-1")

    with factory() as session:
        assert session.get(WorkerBeat, "host-a-1") is None
        assert worker_alive(session) is False


def test_stopping_one_worker_leaves_the_other_beat():
    factory = _factory()
    with factory() as session:
        record_beat(session, name="host-a-1")
        record_beat(session, name="host-b-1")
        session.commit()

    silence_beat(factory, "host-a-1")

    with factory() as session:
        assert session.get(WorkerBeat, "host-a-1") is None
        assert session.get(WorkerBeat, "host-b-1") is not None
        assert worker_alive(session) is True
        assert worker_alive(session, name="host-a-1") is False
        assert worker_alive(session, name="host-b-1") is True


def test_health_stays_up_while_any_beat_is_fresh():
    factory = _factory()
    with factory() as session:
        record_beat(session, name="old")
        record_beat(session, name="new")
        session.commit()
        old = session.get(WorkerBeat, "old")
        old.beat_at = utcnow() - timedelta(seconds=STALE_AFTER_SECONDS + 1)
        session.commit()

    with factory() as session:
        assert worker_alive(session) is True
        assert worker_alive(session, name="old") is False
        assert worker_alive(session, name="new") is True


def test_clear_beat_leaves_other_rows():
    factory = _factory()
    with factory() as session:
        record_beat(session, name="worker")
        record_beat(session, name="other")
        clear_beat(session)
        session.commit()
        assert session.get(WorkerBeat, "worker") is None
        assert session.get(WorkerBeat, "other") is not None


def test_the_heartbeat_loop_writes_its_own_name_until_stopped():
    factory = _factory()
    stop = threading.Event()
    thread = threading.Thread(
        target=run_heartbeat,
        args=(factory, stop, 0.01),
        kwargs={"name": "host-1"},
    )
    thread.start()
    try:
        deadline = utcnow() + timedelta(seconds=2)
        wrote = False
        while utcnow() < deadline:
            with factory() as session:
                wrote = session.get(WorkerBeat, "host-1") is not None
            if wrote:
                break
        assert wrote is True
    finally:
        stop.set()
        thread.join(timeout=2)
    assert thread.is_alive() is False
    silence_beat(factory, "host-1")
    with factory() as session:
        assert session.get(WorkerBeat, "host-1") is None
        assert worker_alive(session) is False


def test_the_process_beat_name_is_the_host_and_the_pid(monkeypatch):
    monkeypatch.setattr(socket, "gethostname", lambda: "checkout-worker.internal")
    monkeypatch.setattr(os, "getpid", lambda: 4242)
    assert process_beat_name() == "checkout-worker-4242"


def test_a_long_host_keeps_the_process_id(monkeypatch):
    monkeypatch.setattr(socket, "gethostname", lambda: "h" * 200)
    monkeypatch.setattr(os, "getpid", lambda: 4242)
    name = process_beat_name()
    assert len(name) == NAME_LIMIT
    assert name.endswith("-4242")
