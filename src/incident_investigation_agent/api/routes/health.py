"""Liveness of the process and readiness of the database."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from incident_investigation_agent.db.session import database_ready

router = APIRouter()


@router.get("/api/health")
def health(request: Request) -> JSONResponse:
    ready = database_ready(request.app.state.session_factory)
    body = {"status": "ok" if ready else "degraded", "database": "ok" if ready else "down"}
    return JSONResponse(status_code=200 if ready else 503, content=body)
