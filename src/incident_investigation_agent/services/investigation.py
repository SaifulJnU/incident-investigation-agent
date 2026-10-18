"""Claim a queued run, ask the agent, and store the incident note."""

from __future__ import annotations

import logging
import time
from datetime import timedelta

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, sessionmaker

from incident_investigation_agent.core.config import Settings
from incident_investigation_agent.core.logging import bind_investigation
from incident_investigation_agent.db.models import Incident, InvestigationRun, WorkerBeat, utcnow
from incident_investigation_agent.db.session import database_ready
from incident_investigation_agent.infrastructure.redact import configured_secrets, redact
from incident_investigation_agent.repositories.cases import DbCaseStore
from incident_investigation_agent.services.agent import build_note_agent
from incident_investigation_agent.services.gather import SearchBatch, gather
from incident_investigation_agent.services.report import IncidentBrief, investigation_prompt, message_text

log = logging.getLogger("incident_investigation_agent.worker")


def release_stale_runs(session: Session, *, older_than_minutes: int) -> int:
    """Fail runs a crashed worker left behind.

    A crash does not get a stop signal, so the row stays ``running`` until
    this cutoff. The unique active-run index then refuses a new investigation.
    """
    cutoff = utcnow() - timedelta(minutes=older_than_minutes)
    runs = list(
        session.scalars(
            select(InvestigationRun).where(
                InvestigationRun.status == "running",
                InvestigationRun.started_at.is_not(None),
                InvestigationRun.started_at < cutoff,
            )
        ).all()
    )
    return _fail_abandoned(session, runs, reason="timeout")


def release_held_runs(session: Session, run_ids) -> int:
    """Fail runs this process still holds.

    A deploy stops the worker while a note is in progress. Those rows are
    released now, including a run that started moments ago. A run this
    process does not hold stays with whoever claimed it.
    """
    ids = list(run_ids)
    if not ids:
        return 0
    runs = list(
        session.scalars(
            select(InvestigationRun).where(
                InvestigationRun.id.in_(ids),
                InvestigationRun.status == "running",
            )
        ).all()
    )
    return _fail_abandoned(session, runs, reason="worker-stopped")


def _fail_abandoned(session: Session, runs, *, reason: str) -> int:
    """Fail runs that are still running. A finished note stays as it is."""
    now = utcnow()
    released = 0
    for run in runs:
        matched = session.scalars(
            update(InvestigationRun)
            .where(
                InvestigationRun.id == run.id,
                InvestigationRun.status == "running",
            )
            .values(
                status="failed",
                error="The worker stopped before this run finished.",
                finished_at=now,
            )
            .returning(InvestigationRun.id)
            .execution_options(synchronize_session=False)
        ).first()
        session.expire(run)
        if matched is None:
            continue
        released += 1
        incident = session.get(Incident, run.incident_id)
        if incident is not None and incident.status == "investigating":
            incident.status = "open"
            incident.updated_at = now
        with bind_investigation(run.incident_id, run.id):
            log.info("investigation released reason=%s", reason)
    return released


def claim_next(session: Session) -> InvestigationRun | None:
    run = session.scalars(
        select(InvestigationRun)
        .where(InvestigationRun.status == "queued")
        .order_by(InvestigationRun.created_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    ).first()
    if run is None:
        return None
    run.status = "running"
    run.started_at = utcnow()
    incident = session.get(Incident, run.incident_id)
    if incident is not None and incident.status == "open":
        incident.status = "investigating"
        incident.updated_at = utcnow()
    return run


def claim_batch(session: Session, limit: int) -> list[InvestigationRun]:
    """Claim several queued runs. Each run stays tied to its own case."""
    runs = list(
        session.scalars(
            select(InvestigationRun)
            .where(InvestigationRun.status == "queued")
            .order_by(InvestigationRun.created_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        ).all()
    )
    now = utcnow()
    for run in runs:
        run.status = "running"
        run.started_at = now
        incident = session.get(Incident, run.incident_id)
        if incident is not None and incident.status == "open":
            incident.status = "investigating"
            incident.updated_at = now
    return runs


def execute(factory: sessionmaker[Session], settings: Settings, run_id, investigate=None) -> None:
    model_name = (
        settings.ollama_model if settings.model_provider == "ollama" else settings.bedrock_model_id
    )
    with factory() as session:
        now = utcnow()
        incident_id = session.scalars(
            update(InvestigationRun)
            .where(
                InvestigationRun.id == run_id,
                InvestigationRun.status.notin_(("completed", "failed")),
            )
            .values(
                status="running",
                started_at=func.coalesce(InvestigationRun.started_at, now),
                provider=settings.model_provider,
                model_name=model_name,
            )
            .returning(InvestigationRun.incident_id)
            .execution_options(synchronize_session=False)
        ).first()
        if incident_id is None:
            session.rollback()
            return
        incident = session.get(Incident, incident_id)
        if incident is None:
            session.rollback()
            missing = True
        else:
            missing = False
            if incident.status == "open":
                incident.status = "investigating"
                incident.updated_at = now
            brief = IncidentBrief(
                title=incident.title,
                service=incident.service,
                severity=incident.severity,
                summary=incident.summary,
                started_at=incident.started_at,
            )
            service_name = incident.service
            session.commit()

    if missing:
        with bind_investigation(None, run_id):
            log.error("investigation failed reason=case-not-found")
        _finish(factory, run_id, status="failed", error="Case not found.")
        return

    store = DbCaseStore(factory, incident_id)
    prompt = investigation_prompt(brief, store.list())
    runner = investigate or _investigate_with_agent
    started = time.perf_counter()
    with bind_investigation(incident_id, run_id):
        log.info(
            "investigation started service=%s provider=%s",
            service_name,
            settings.model_provider,
        )
        try:
            report = runner(settings, store, prompt, service_name)
        except Exception as exc:
            safe = redact(str(exc), configured_secrets(settings))[:2000]
            detail = safe.splitlines()[0][:300] if safe else exc.__class__.__name__
            log.error("investigation failed error=%s", detail)
            _finish(factory, run_id, status="failed", error=safe or exc.__class__.__name__)
            return
        if _finish(factory, run_id, status="completed", report=report):
            log.info("investigation completed seconds=%.2f", time.perf_counter() - started)
            return
        log.info("investigation already finished seconds=%.2f", time.perf_counter() - started)


def run_once(factory: sessionmaker[Session], settings: Settings, investigate=None) -> bool:
    runner = investigate or _investigate_with_agent
    with factory() as session:
        run = claim_next(session)
        if run is None:
            session.rollback()
            return False
        run_id = run.id
        session.commit()
    execute(factory, settings, run_id, runner)
    return True


def _investigate_with_agent(settings: Settings, store: DbCaseStore, prompt: str, service: str) -> str:
    batch = gather(settings, service, prompt)
    _record_findings(store, batch.findings)
    note = _note_prompt(prompt, batch)
    return message_text(build_note_agent(settings)(note))


def _record_findings(store, findings) -> None:
    """Skip a line the case already has, so a second run does not copy it."""
    existing = {item.summary for item in store.list()}
    for item in findings:
        summary = item.summary.strip()
        if not summary or summary in existing:
            continue
        store.add(item.kind, summary, item.source)
        existing.add(summary)


def _note_prompt(prompt: str, batch: SearchBatch) -> str:
    """One copy of each matching line, then what was not checked."""
    marker = "Start by calling search_logs."
    base = prompt.split(marker)[0].rstrip() if marker in prompt else prompt.rstrip()
    parts = [base, "", "Matching lines:"]
    if batch.findings:
        parts.extend(item.summary for item in batch.findings)
    else:
        parts.append("No matching lines.")
    if batch.unchecked:
        parts.extend(["", "Sources that were not checked:"])
        parts.extend(batch.unchecked)
    if batch.misses:
        parts.extend(["", "No match for " + ", ".join(batch.misses) + "."])
    parts.extend(["", "Write the incident note from these lines."])
    return "\n".join(parts)


def _finish(
    factory: sessionmaker[Session],
    run_id,
    *,
    status: str,
    report: str | None = None,
    error: str | None = None,
) -> bool:
    """Store this outcome once. A later finish leaves the first note in place."""
    with factory() as session:
        now = utcnow()
        incident_id = session.scalars(
            update(InvestigationRun)
            .where(
                InvestigationRun.id == run_id,
                InvestigationRun.status.notin_(("completed", "failed")),
            )
            .values(
                status=status,
                report=report,
                error=error,
                finished_at=now,
            )
            .returning(InvestigationRun.incident_id)
            .execution_options(synchronize_session=False)
        ).first()
        if incident_id is None:
            session.rollback()
            return False
        incident = session.get(Incident, incident_id)
        if incident is not None and incident.status == "investigating":
            incident.status = "open"
            incident.updated_at = now
        session.commit()
        return True


def wait_for_database(factory: sessionmaker[Session]) -> None:
    for _ in range(60):
        if database_ready(factory):
            try:
                with factory() as session:
                    session.execute(select(InvestigationRun).limit(1))
                    session.execute(select(WorkerBeat).limit(1))
                return
            except Exception:
                log.info("waiting for schema")
        time.sleep(1)
    raise SystemExit("Database schema is not ready.")
