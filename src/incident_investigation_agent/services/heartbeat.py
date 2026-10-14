"""The worker writes a timestamp. Health reads it."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from incident_investigation_agent.db.models import WorkerBeat, utcnow

BEAT_NAME = "worker"
BEAT_INTERVAL_SECONDS = 5
STALE_AFTER_SECONDS = 20


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
    name: str = BEAT_NAME,
) -> bool:
    """True when this worker has written a beat inside the window.

    A crash leaves the last timestamp in place. Once that timestamp is older
    than the window, health reports the worker down.
    """
    row = session.get(WorkerBeat, name)
    if row is None:
        return False
    age = utcnow() - _aware(row.beat_at)
    return age <= timedelta(seconds=stale_after_seconds)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value
