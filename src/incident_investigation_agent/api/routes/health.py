"""Liveness of the API, the database, and the worker."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from incident_investigation_agent.db.session import database_ready
from incident_investigation_agent.services.heartbeat import worker_alive

router = APIRouter()


@router.get("/api/health")
def health(request: Request) -> JSONResponse:
    factory = request.app.state.session_factory
    if not database_ready(factory):
        body = {"status": "degraded", "database": "down", "worker": "unknown"}
        return JSONResponse(status_code=503, content=body)
    try:
        with factory() as session:
            alive = worker_alive(session)
    except Exception:
        alive = False
    body = {
        "status": "ok" if alive else "degraded",
        "database": "ok",
        "worker": "ok" if alive else "down",
    }
    return JSONResponse(status_code=200 if alive else 503, content=body)
