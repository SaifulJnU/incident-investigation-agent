"""FastAPI dependencies. The session is opened and closed here, not in a route."""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from incident_investigation_agent.domain.access import Principal
from incident_investigation_agent.infrastructure.auth import AuthError, verify_access_token

_bearer = HTTPBearer(auto_error=False)


def get_db(request: Request) -> Iterator[Session]:
    session = request.app.state.session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_principal(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> Principal:
    if credentials is None or credentials.scheme.lower() != "bearer" or not credentials.credentials:
        raise HTTPException(
            status_code=401,
            detail="Sign in required.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        return verify_access_token(request.app.state.settings, credentials.credentials)
    except AuthError as exc:
        raise HTTPException(
            status_code=401,
            detail="Sign-in expired or not accepted.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
