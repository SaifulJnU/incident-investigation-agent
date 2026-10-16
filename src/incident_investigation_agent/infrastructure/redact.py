"""Strip secrets from text that will be stored or shown.

HTTP responses already drop header values. A failed run and a connector
exception are stored too, and those strings are not an HTTP body.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterable

from incident_investigation_agent.core.config import Settings

_BEARER = re.compile(r"(?i)(Bearer\s+)[A-Za-z0-9._~+/=-]{8,}")
_AWS_ACCESS_KEY = re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")
_GITHUB_TOKEN = re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}\b")
_GITHUB_PAT = re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b")
_URL_PASSWORD = re.compile(r"(://[^/\s:@]+:)([^/\s@]+)@")
_ENV_SECRETS = ("AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN", "AWS_ACCESS_KEY_ID")


def redact(text: str, secrets: Iterable[str] = ()) -> str:
    """Replace known secrets and token shapes. Short values are left as written."""
    redacted = text
    ordered = sorted(
        {value.strip() for value in secrets if len(value.strip()) >= 8},
        key=len,
        reverse=True,
    )
    for secret in ordered:
        redacted = redacted.replace(secret, "[redacted]")
        if secret.lower().startswith("bearer "):
            token = secret.split(None, 1)[1]
            if len(token) >= 8:
                redacted = redacted.replace(token, "[redacted]")
    redacted = _BEARER.sub(r"\1[redacted]", redacted)
    redacted = _AWS_ACCESS_KEY.sub("[redacted]", redacted)
    redacted = _GITHUB_TOKEN.sub("[redacted]", redacted)
    redacted = _GITHUB_PAT.sub("[redacted]", redacted)
    redacted = _URL_PASSWORD.sub(r"\1[redacted]@", redacted)
    return redacted


def configured_secrets(settings: Settings) -> tuple[str, ...]:
    """Secrets this process was given, so a non-HTTP exception cannot keep them."""
    values = [
        settings.datadog_api_key,
        settings.datadog_app_key,
        settings.loki_token,
        settings.github_token,
        settings.dev_auth_secret,
    ]
    values.extend(user.password for user in settings.dev_users)
    password = _database_password(settings.database_url)
    if password:
        values.append(password)
    for name in _ENV_SECRETS:
        raw = os.environ.get(name, "")
        if raw.strip():
            values.append(raw.strip())
    return tuple(values)


def _database_password(url: str) -> str:
    match = _URL_PASSWORD.search(url)
    if match is None:
        return ""
    return match.group(2)
