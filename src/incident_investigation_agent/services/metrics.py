"""Counts an operator can read without opening a case."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from incident_investigation_agent.db.models import InvestigationRun, utcnow

WINDOW = timedelta(hours=1)


def investigation_metrics(session: Session, *, now: datetime | None = None) -> dict:
    """Queue depth and how many runs finished in the last hour.

    The result is counts and one age. It does not include a title, a note,
    or a line of evidence.
    """
    moment = now or utcnow()
    since = moment - WINDOW
    return {
        "queued": _count(session, "queued"),
        "running": _count(session, "running"),
        "completed_last_hour": _finished(session, "completed", since),
        "failed_last_hour": _finished(session, "failed", since),
        "oldest_queued_seconds": _oldest_queued_seconds(session, moment),
    }


def _count(session: Session, status: str) -> int:
    query = select(func.count()).select_from(InvestigationRun).where(InvestigationRun.status == status)
    return int(session.scalar(query) or 0)


def _finished(session: Session, status: str, since: datetime) -> int:
    query = (
        select(func.count())
        .select_from(InvestigationRun)
        .where(
            InvestigationRun.status == status,
            InvestigationRun.finished_at.is_not(None),
            InvestigationRun.finished_at >= since,
        )
    )
    return int(session.scalar(query) or 0)


def _oldest_queued_seconds(session: Session, now: datetime) -> int | None:
    query = select(func.min(InvestigationRun.created_at)).where(InvestigationRun.status == "queued")
    oldest = session.scalar(query)
    if oldest is None:
        return None
    age = int((now - _aware(oldest)).total_seconds())
    if age < 0:
        return 0
    return age


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value
