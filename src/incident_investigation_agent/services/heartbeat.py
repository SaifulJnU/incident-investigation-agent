"""Each worker process writes its own timestamp. Health reads them."""

from __future__ import annotations

import os
import socket
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from incident_investigation_agent.db.models import WorkerBeat, utcnow

BEAT_NAME = "worker"
BEAT_INTERVAL_SECONDS = 5
STALE_AFTER_SECONDS = 20
NAME_LIMIT = 128


def process_beat_name() -> str:
    """A name that belongs to this process.

    The host distinguishes containers that share a pid. The pid distinguishes
    two processes on one host. A long host keeps its end, which is the unique
    part, and the process id.
    """
    host = socket.gethostname().split(".")[0].strip() or "worker"
    name = f"{host}-{os.getpid()}"
    if len(name) <= NAME_LIMIT:
        return name
    return name[-NAME_LIMIT:]


def record_beat(session: Session, *, name: str = BEAT_NAME) -> None:
    now = utcnow()
    row = session.get(WorkerBeat, name)
    if row is None:
        session.add(WorkerBeat(name=name, beat_at=now))
        return
    row.beat_at = now


def clear_beat(session: Session, *, name: str = BEAT_NAME) -> None:
    row = session.get(WorkerBeat, name)
    if row is not None:
        session.delete(row)


def worker_alive(
    session: Session,
    *,
    stale_after_seconds: int = STALE_AFTER_SECONDS,
    name: str | None = None,
) -> bool:
    """True when a worker has written a beat inside the window.

    With no name, any fresh row is enough, so one live process keeps health
    up. A name checks that process alone. A crash leaves the last timestamp
    in place. Once that timestamp is older than the window, that row no
    longer counts.
    """
    if name is None:
        rows = session.scalars(select(WorkerBeat)).all()
        return any(_fresh(row.beat_at, stale_after_seconds) for row in rows)
    row = session.get(WorkerBeat, name)
    if row is None:
        return False
    return _fresh(row.beat_at, stale_after_seconds)


def _fresh(beat_at: datetime, stale_after_seconds: int) -> bool:
    age = utcnow() - _aware(beat_at)
    return age <= timedelta(seconds=stale_after_seconds)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value
