"""Claim queued investigations and write the incident note back to the case."""

from __future__ import annotations

import logging
import os
import time

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from incident_investigation_agent.agent import build_agent
from incident_investigation_agent.config import Settings
from incident_investigation_agent.db import session_factory_from_url
from incident_investigation_agent.records import DbCaseStore
from incident_investigation_agent.report import IncidentBrief, investigation_prompt, message_text
from incident_investigation_agent.schema import Incident, InvestigationRun, utcnow

log = logging.getLogger("incident_investigation_agent.worker")


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


def execute(factory: sessionmaker[Session], settings: Settings, run_id, investigate) -> None:
    with factory() as session:
        run = session.get(InvestigationRun, run_id)
        if run is None or run.status in {"completed", "failed"}:
            return
        incident = session.get(Incident, run.incident_id)
        if incident is None:
            run.status = "failed"
            run.error = "Case not found."
            run.finished_at = utcnow()
            session.commit()
            return
        run.status = "running"
        run.started_at = run.started_at or utcnow()
        run.provider = settings.model_provider
        run.model_name = (
            settings.ollama_model
            if settings.model_provider == "ollama"
            else settings.bedrock_model_id
        )
        if incident.status == "open":
            incident.status = "investigating"
            incident.updated_at = utcnow()
        brief = IncidentBrief(
            title=incident.title,
            service=incident.service,
            severity=incident.severity,
            summary=incident.summary,
            started_at=incident.started_at,
        )
        incident_id = incident.id
        session.commit()

    store = DbCaseStore(factory, incident_id)
    prompt = investigation_prompt(brief, store.list())
    try:
        report = investigate(settings, store, prompt)
    except Exception as exc:
        log.exception("investigation failed run=%s", run_id)
        _finish(factory, run_id, status="failed", error=str(exc)[:2000])
        return
    _finish(factory, run_id, status="completed", report=report)


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


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(levelname)s %(name)s %(message)s",
    )
    settings = Settings.from_env()
    if not settings.database_url.startswith("postgresql"):
        raise SystemExit("The worker requires PostgreSQL.")
    factory = session_factory_from_url(settings.database_url)
    _wait_for_database(factory)
    log.info("worker ready provider=%s", settings.model_provider)
    while True:
        try:
            worked = run_once(factory, settings)
        except Exception:
            log.exception("worker loop failed")
            worked = False
        if not worked:
            time.sleep(1)


def _investigate_with_agent(settings: Settings, store: DbCaseStore, prompt: str) -> str:
    agent = build_agent(settings, store=store)
    return message_text(agent(prompt))


def _finish(factory: sessionmaker[Session], run_id, *, status: str, report: str | None = None, error: str | None = None) -> None:
    with factory() as session:
        run = session.get(InvestigationRun, run_id)
        if run is None:
            return
        incident = session.get(Incident, run.incident_id)
        run.status = status
        run.report = report
        run.error = error
        run.finished_at = utcnow()
        if incident is not None and incident.status == "investigating":
            incident.status = "open"
            incident.updated_at = utcnow()
        session.commit()


def _wait_for_database(factory: sessionmaker[Session]) -> None:
    from incident_investigation_agent.db import database_ready

    for _ in range(60):
        if database_ready(factory):
            try:
                with factory() as session:
                    session.execute(select(InvestigationRun).limit(1))
                return
            except Exception:
                log.info("waiting for schema")
        time.sleep(1)
    raise SystemExit("Database schema is not ready.")


if __name__ == "__main__":
    main()
