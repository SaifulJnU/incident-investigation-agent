"""Case file routes. They validate input, call the repository, and return DTOs."""

from __future__ import annotations

import uuid
from datetime import timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from incident_investigation_agent.api.dependencies import get_db
from incident_investigation_agent.api.schemas import (
    EvidenceCreate,
    IncidentCreate,
    IncidentDetail,
    IncidentOut,
    IncidentPatch,
    RunOut,
)
from incident_investigation_agent.core.config import Settings
from incident_investigation_agent.db.models import utcnow
from incident_investigation_agent.repositories.cases import (
    active_run,
    add_evidence,
    evidence_for,
    get_incident,
    list_incidents,
    open_incident,
    queue_run,
    runs_for,
)

router = APIRouter()


@router.get("/api/incidents", response_model=list[IncidentOut])
def incidents(session: Session = Depends(get_db)) -> list:
    return list_incidents(session)


@router.post("/api/incidents", response_model=IncidentOut, status_code=201)
def create_incident(body: IncidentCreate, session: Session = Depends(get_db)):
    started = body.started_at or utcnow()
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    return open_incident(
        session,
        title=body.title,
        summary=body.summary,
        service=body.service,
        severity=body.severity,
        started_at=started,
    )


@router.get("/api/incidents/{incident_id}", response_model=IncidentDetail)
def incident_detail(incident_id: uuid.UUID, session: Session = Depends(get_db)):
    return _detail(session, _require(session, incident_id))


@router.patch("/api/incidents/{incident_id}", response_model=IncidentOut)
def update_incident(
    incident_id: uuid.UUID,
    body: IncidentPatch,
    session: Session = Depends(get_db),
):
    incident = _require(session, incident_id)
    if body.status is not None:
        incident.status = body.status
    if body.severity is not None:
        incident.severity = body.severity
    if body.summary is not None:
        incident.summary = body.summary
    incident.updated_at = utcnow()
    session.flush()
    return incident


@router.post(
    "/api/incidents/{incident_id}/evidence",
    response_model=IncidentDetail,
    status_code=201,
)
def create_evidence(
    incident_id: uuid.UUID,
    body: EvidenceCreate,
    session: Session = Depends(get_db),
):
    incident = _require(session, incident_id)
    add_evidence(
        session,
        incident.id,
        kind=body.kind,
        summary=body.summary,
        source="operator",
    )
    incident.updated_at = utcnow()
    session.flush()
    return _detail(session, incident)


@router.post(
    "/api/incidents/{incident_id}/investigate",
    response_model=RunOut,
    status_code=202,
)
def investigate(incident_id: uuid.UUID, session: Session = Depends(get_db)):
    incident = _require(session, incident_id)
    if incident.status == "resolved":
        raise HTTPException(status_code=409, detail="This case is resolved.")
    if active_run(session, incident.id) is not None:
        raise HTTPException(
            status_code=409,
            detail="An investigation is already running for this case.",
        )
    settings = Settings.from_env()
    model_name = (
        settings.ollama_model
        if settings.model_provider == "ollama"
        else settings.bedrock_model_id
    )
    try:
        run = queue_run(
            session,
            incident,
            provider=settings.model_provider,
            model_name=model_name,
        )
    except IntegrityError:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail="An investigation is already running for this case.",
        ) from None
    return run


def _detail(session: Session, incident):
    return {
        "id": incident.id,
        "title": incident.title,
        "summary": incident.summary,
        "service": incident.service,
        "severity": incident.severity,
        "status": incident.status,
        "started_at": incident.started_at,
        "created_at": incident.created_at,
        "updated_at": incident.updated_at,
        "evidence": [
            {
                "id": item.id,
                "kind": item.kind,
                "summary": item.summary,
                "source": item.source,
                "recorded_at": item.recorded_at,
            }
            for item in evidence_for(session, incident.id)
        ],
        "runs": [
            {
                "id": run.id,
                "status": run.status,
                "provider": run.provider,
                "model_name": run.model_name,
                "report": run.report,
                "error": run.error,
                "created_at": run.created_at,
                "started_at": run.started_at,
                "finished_at": run.finished_at,
            }
            for run in runs_for(session, incident.id)
        ],
    }


def _require(session: Session, incident_id: uuid.UUID):
    incident = get_incident(session, incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="Case not found.")
    return incident
