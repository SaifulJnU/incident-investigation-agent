"""Sign-in. Health stays open. Every case route requires a principal."""

from __future__ import annotations

import hmac

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from incident_investigation_agent.api.dependencies import get_principal
from incident_investigation_agent.core.config import Settings
from incident_investigation_agent.domain.access import Principal
from incident_investigation_agent.infrastructure.auth import (
    AuthError,
    issue_dev_token,
    oidc_metadata,
)

router = APIRouter()


class DevLogin(BaseModel):
    subject: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=1, max_length=200)


def _settings(request: Request) -> Settings:
    return request.app.state.settings


@router.get("/api/auth/config")
def auth_config(request: Request):
    settings = _settings(request)
    if settings.auth_mode == "dev":
        return {"mode": "dev"}
    try:
        metadata = oidc_metadata(settings)
    except AuthError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    authorization = metadata.get("authorization_endpoint")
    token = metadata.get("token_endpoint")
    if not authorization or not token or not settings.oidc_client_id:
        raise HTTPException(status_code=503, detail="The identity provider is not configured.")
    return {
        "mode": "oidc",
        "issuer": settings.oidc_issuer,
        "client_id": settings.oidc_client_id,
        "audience": settings.token_audience,
        "authorization_endpoint": authorization,
        "token_endpoint": token,
    }


@router.post("/api/auth/dev/token")
def dev_token(body: DevLogin, request: Request):
    settings = _settings(request)
    if settings.auth_mode != "dev":
        raise HTTPException(status_code=404, detail="Not found.")
    user = next((item for item in settings.dev_users if item.subject == body.subject.strip()), None)
    if user is None or not hmac.compare_digest(user.password, body.password):
        raise HTTPException(status_code=401, detail="Sign-in was not accepted.")
    issued = issue_dev_token(settings, user)
    return {
        "access_token": issued.access_token,
        "token_type": "Bearer",
        "expires_in": issued.expires_in,
        "subject": issued.principal.subject,
        "name": issued.principal.name,
        "services": sorted(issued.principal.services),
    }


@router.get("/api/auth/me")
def me(principal: Principal = Depends(get_principal)):
    return {
        "subject": principal.subject,
        "name": principal.name,
        "services": sorted(principal.services),
        "allows_all": principal.allows_all,
    }
