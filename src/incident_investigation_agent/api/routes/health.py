"""Liveness, readiness, and the operator view of the database and the worker.

Liveness answers when the process is up. It does not touch the database.
Readiness answers only when the case schema can be read. A process that is
up and waiting on the database fails readiness and still passes liveness.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from incident_investigation_agent.db.session import schema_ready
from incident_investigation_agent.services.heartbeat import worker_alive
from incident_investigation_agent.services.metrics import investigation_metrics

router = APIRouter()


@router.get("/api/live")
def live() -> JSONResponse:
    return JSONResponse(status_code=200, content={"status": "ok"})


@router.get("/api/ready")
def ready(request: Request) -> JSONResponse:
    factory = request.app.state.session_factory
    if not schema_ready(factory):
        body = {"status": "unavailable", "database": "down"}
        return JSONResponse(status_code=503, content=body)
    return JSONResponse(status_code=200, content={"status": "ok", "database": "ok"})


@router.get("/api/health")
def health(request: Request) -> JSONResponse:
    factory = request.app.state.session_factory
    if not schema_ready(factory):
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


@router.get("/api/metrics")
def metrics(request: Request) -> JSONResponse:
    """Queue depth only. A database that is down must not look like an empty queue."""
    factory = request.app.state.session_factory
    if not schema_ready(factory):
        body = {"status": "unavailable", "database": "down"}
        return JSONResponse(status_code=503, content=body)
    try:
        with factory() as session:
            body = investigation_metrics(session)
    except Exception:
        body = {"status": "unavailable", "database": "down"}
        return JSONResponse(status_code=503, content=body)
    return JSONResponse(status_code=200, content=body)
