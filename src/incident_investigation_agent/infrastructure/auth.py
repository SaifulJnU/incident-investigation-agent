"""Verify a bearer token and issue local tokens for the development stack."""

from __future__ import annotations

import json
import time
import urllib.request
from dataclasses import dataclass
from urllib.error import URLError

import jwt
from jwt import PyJWKClient

from incident_investigation_agent.core.config import DevUser, Settings
from incident_investigation_agent.domain.access import Principal

DEV_ISSUER = "http://case-file.local/dev"
_DEV_TTL_SECONDS = 8 * 60 * 60
_metadata_cache: dict[str, dict] = {}
_jwks_clients: dict[str, PyJWKClient] = {}


class AuthError(Exception):
    """The bearer token is missing, expired, or not issued for this API."""


@dataclass(frozen=True)
class IssuedToken:
    access_token: str
    expires_in: int
    principal: Principal


def issue_dev_token(settings: Settings, user: DevUser) -> IssuedToken:
    if settings.auth_mode != "dev":
        raise AuthError("Local sign-in is disabled.")
    now = int(time.time())
    services = sorted(user.services)
    roles = ["incident-admin"] if user.allows_all else []
    payload = {
        "iss": DEV_ISSUER,
        "aud": settings.token_audience,
        "sub": user.subject,
        "name": user.name,
        "services": services,
        "roles": roles,
        "iat": now,
        "exp": now + _DEV_TTL_SECONDS,
    }
    token = jwt.encode(payload, settings.dev_auth_secret, algorithm="HS256")
    principal = Principal(
        subject=user.subject,
        name=user.name,
        services=frozenset(services),
        roles=frozenset(roles),
    )
    return IssuedToken(access_token=token, expires_in=_DEV_TTL_SECONDS, principal=principal)


def verify_access_token(settings: Settings, token: str) -> Principal:
    if settings.auth_mode == "dev":
        return _verify_dev(settings, token)
    return _verify_oidc(settings, token)


def oidc_metadata(settings: Settings) -> dict:
    issuer = settings.oidc_issuer.rstrip("/")
    cached = _metadata_cache.get(issuer)
    if cached is not None:
        return cached
    url = f"{issuer}/.well-known/openid-configuration"
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            metadata = json.loads(response.read().decode("utf-8"))
    except (URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        raise AuthError("The identity provider is not reachable.") from exc
    if not isinstance(metadata, dict):
        raise AuthError("The identity provider is not reachable.")
    _metadata_cache[issuer] = metadata
    return metadata


def _verify_dev(settings: Settings, token: str) -> Principal:
    try:
        payload = jwt.decode(
            token,
            settings.dev_auth_secret,
            algorithms=["HS256"],
            audience=settings.token_audience,
            issuer=DEV_ISSUER,
            leeway=30,
        )
    except jwt.PyJWTError as exc:
        raise AuthError("Sign-in expired or not accepted.") from exc
    return _principal(payload, service_claim="services", role_claim="roles")


def _verify_oidc(settings: Settings, token: str) -> Principal:
    jwks_url = settings.oidc_jwks_url or str(oidc_metadata(settings).get("jwks_uri") or "")
    if not jwks_url:
        raise AuthError("The identity provider is not reachable.")
    client = _jwks_clients.get(jwks_url)
    if client is None:
        client = PyJWKClient(jwks_url, timeout=5)
        _jwks_clients[jwks_url] = client
    try:
        signing_key = client.get_signing_key_from_jwt(token)
        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256", "RS384", "RS512", "ES256"],
            audience=settings.token_audience,
            issuer=settings.oidc_issuer,
            leeway=30,
        )
    except (jwt.PyJWTError, AuthError) as exc:
        raise AuthError("Sign-in expired or not accepted.") from exc
    return _principal(
        payload,
        service_claim=settings.oidc_service_claim,
        role_claim=settings.oidc_role_claim,
    )


def _principal(payload: dict, *, service_claim: str, role_claim: str) -> Principal:
    subject = str(payload.get("sub") or "").strip()
    if not subject:
        raise AuthError("Sign-in expired or not accepted.")
    name = str(payload.get("name") or payload.get("preferred_username") or subject).strip()
    return Principal(
        subject=subject[:200],
        name=name[:200] or subject[:200],
        services=_claim_set(payload.get(service_claim)),
        roles=_claim_set(payload.get(role_claim)),
    )


def _claim_set(value: object) -> frozenset[str]:
    if isinstance(value, str):
        parts = value.replace(";", ",").split(",")
    elif isinstance(value, list):
        parts = [str(item) for item in value]
    else:
        return frozenset()
    return frozenset(part.strip() for part in parts if part.strip())
