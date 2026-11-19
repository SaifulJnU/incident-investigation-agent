"""Counts an operator can read without opening a case."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from incident_investigation_agent.db.models import InvestigationRun, utcnow
from incident_investigation_agent.services.heartbeat import fresh_worker_count

WINDOW = timedelta(hours=1)


_GAUGES = (
    ("queued", "case_file_runs_queued", "Runs waiting to be claimed."),
    ("running", "case_file_runs_running", "Runs a worker has claimed."),
    (
        "completed_last_hour",
        "case_file_runs_completed_last_hour",
        "Runs that completed in the last hour.",
    ),
    (
        "failed_last_hour",
        "case_file_runs_failed_last_hour",
        "Runs that failed in the last hour.",
    ),
    (
        "workers",
        "case_file_workers",
        "Worker processes with a fresh heartbeat.",
    ),
)


def prometheus_text(body: dict) -> str:
    """The same counts as Prometheus text. No title, note, service, or host.

    An empty queue omits the age gauge. A missing age is not zero seconds.
    Zero workers stays, because a dead fleet is not a missing sample.
    """
    lines: list[str] = []
    for key, name, help_text in _GAUGES:
        lines.append(f"# HELP {name} {help_text}")
        lines.append(f"# TYPE {name} gauge")
        lines.append(f"{name} {int(body[key])}")
    age = body["oldest_queued_seconds"]
    if age is not None:
        lines.append(
            "# HELP case_file_oldest_queued_seconds "
            "Seconds the oldest waiting run has been queued."
        )
        lines.append("# TYPE case_file_oldest_queued_seconds gauge")
        lines.append(f"case_file_oldest_queued_seconds {int(age)}")
    return "\n".join(lines) + "\n"


def investigation_metrics(session: Session, *, now: datetime | None = None) -> dict:
    """Queue depth, how many runs finished in the last hour, and live workers.

    The result is counts and one age. It does not include a title, a note,
    a line of evidence, or a host name. A stale heartbeat does not count.
    """
    moment = now or utcnow()
    since = moment - WINDOW
    return {
        "queued": _count(session, "queued"),
        "running": _count(session, "running"),
        "completed_last_hour": _finished(session, "completed", since),
        "failed_last_hour": _finished(session, "failed", since),
        "oldest_queued_seconds": _oldest_queued_seconds(session, moment),
        "workers": fresh_worker_count(session),
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
