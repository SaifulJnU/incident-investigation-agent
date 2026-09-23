"""Runtime settings. Production defaults to Amazon Bedrock and OIDC."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _env(name: str, default: str) -> str:
    value = os.environ.get(name)
    if value is None or not value.strip():
        return default
    return value.strip()


@dataclass(frozen=True)
class DevUser:
    subject: str
    name: str
    services: frozenset[str]
    password: str

    @property
    def allows_all(self) -> bool:
        return "*" in self.services


def parse_dev_users(raw: str) -> tuple[DevUser, ...]:
    users: list[DevUser] = []
    for entry in raw.split(";"):
        entry = entry.strip()
        if not entry:
            continue
        parts = [part.strip() for part in entry.split("|")]
        if len(parts) != 4 or not parts[0] or not parts[3]:
            raise ValueError(
                "DEV_USERS entries are subject|name|services|password, "
                "separated by semicolons."
            )
        services = frozenset(item.strip() for item in parts[2].split(",") if item.strip())
        if not services:
            raise ValueError(f"DEV_USERS entry {parts[0]!r} has no services.")
        users.append(
            DevUser(
                subject=parts[0],
                name=parts[1] or parts[0],
                services=services,
                password=parts[3],
            )
        )
    return tuple(users)


@dataclass(frozen=True)
class Settings:
    model_provider: str
    ollama_host: str
    ollama_model: str
    bedrock_model_id: str
    aws_region: str
    log_dir: Path
    case_dir: Path
    database_url: str
    auth_mode: str = "oidc"
    oidc_issuer: str = ""
    oidc_audience: str = "case-file"
    oidc_jwks_url: str = ""
    oidc_client_id: str = ""
    oidc_service_claim: str = "services"
    oidc_role_claim: str = "roles"
    dev_auth_secret: str = ""
    dev_users: tuple[DevUser, ...] = ()

    @property
    def token_audience(self) -> str:
        return self.oidc_audience or "case-file"

    @classmethod
    def from_env(cls) -> Settings:
        provider = _env("MODEL_PROVIDER", "bedrock").lower()
        if provider not in {"bedrock", "ollama"}:
            raise ValueError(
                "MODEL_PROVIDER must be 'bedrock' or 'ollama', "
                f"got {provider!r}"
            )
        auth_mode = _env("AUTH_MODE", "oidc").lower()
        if auth_mode not in {"oidc", "dev"}:
            raise ValueError("AUTH_MODE must be 'oidc' or 'dev', " f"got {auth_mode!r}")
        issuer = _env("OIDC_ISSUER", "")
        audience = _env("OIDC_AUDIENCE", "case-file")
        secret = _env("DEV_AUTH_SECRET", "")
        users = parse_dev_users(_env("DEV_USERS", ""))
        if auth_mode == "oidc" and not issuer:
            raise ValueError("OIDC_ISSUER is required when AUTH_MODE=oidc.")
        if auth_mode == "dev":
            if len(secret) < 16:
                raise ValueError(
                    "DEV_AUTH_SECRET must be at least 16 characters when AUTH_MODE=dev."
                )
            if not users:
                raise ValueError("DEV_USERS is required when AUTH_MODE=dev.")
        return cls(
            model_provider=provider,
            ollama_host=_env("OLLAMA_HOST", "http://localhost:11434"),
            ollama_model=_env("OLLAMA_MODEL", "llama3.1"),
            bedrock_model_id=_env(
                "BEDROCK_MODEL_ID", "global.anthropic.claude-sonnet-4-6"
            ),
            aws_region=_env("AWS_REGION", "us-west-2"),
            log_dir=Path(_env("LOG_DIR", "examples/logs")),
            case_dir=Path(_env("CASE_DIR", ".case")),
            database_url=_env(
                "DATABASE_URL",
                "postgresql+psycopg://investigator:investigator@localhost:5432/investigations",
            ),
            auth_mode=auth_mode,
            oidc_issuer=issuer,
            oidc_audience=audience,
            oidc_jwks_url=_env("OIDC_JWKS_URL", ""),
            oidc_client_id=_env("OIDC_CLIENT_ID", ""),
            oidc_service_claim=_env("OIDC_SERVICE_CLAIM", "services"),
            oidc_role_claim=_env("OIDC_ROLE_CLAIM", "roles"),
            dev_auth_secret=secret,
            dev_users=users,
        )
