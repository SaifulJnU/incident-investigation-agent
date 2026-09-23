"""Case file API. Routes are mounted here; investigations are finished by the worker."""

from __future__ import annotations

import uuid

from fastapi import FastAPI, Request
from sqlalchemy.orm import Session, sessionmaker

from incident_investigation_agent.api.routes.auth import router as auth_router
from incident_investigation_agent.api.routes.health import router as health_router
from incident_investigation_agent.api.routes.incidents import router as incidents_router
from incident_investigation_agent.core.config import Settings
from incident_investigation_agent.db.session import session_factory_from_url


def create_app(
    session_factory: sessionmaker[Session] | None = None,
    settings: Settings | None = None,
) -> FastAPI:
    app = FastAPI(title="Case file")
    resolved = settings or Settings.from_env()
    if session_factory is None:
        session_factory = session_factory_from_url(resolved.database_url)
    app.state.session_factory = session_factory
    app.state.settings = resolved

    @app.middleware("http")
    async def request_id(request: Request, call_next):
        incoming = request.headers.get("x-request-id") or str(uuid.uuid4())
        response = await call_next(request)
        response.headers["x-request-id"] = incoming
        return response

    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(incidents_router)
    return app


app = create_app()
