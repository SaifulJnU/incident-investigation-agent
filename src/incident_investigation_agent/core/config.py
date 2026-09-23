"""Runtime settings. Production defaults to Amazon Bedrock and OIDC."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# local_logs reads LOG_DIR. The others read company systems when APP_ENV=prod.
KNOWN_CONNECTORS = ("local_logs", "cloudwatch", "datadog", "loki", "github")
PRODUCTION_CONNECTORS = ("cloudwatch", "datadog", "loki", "github")


def _env(name: str, default: str) -> str:
    value = os.environ.get(name)
    if value is None or not value.strip():
        return default
    return value.strip()


def _int_env(name: str, default: int, low: int, high: int) -> int:
    raw = _env(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer.") from exc
    if value < low or value > high:
        raise ValueError(f"{name} must be between {low} and {high}.")
    return value


def parse_connectors(raw: str) -> tuple[str, ...]:
    names: list[str] = []
    for part in raw.split(","):
        name = part.strip().lower()
        if not name:
            continue
        if name not in KNOWN_CONNECTORS:
            known = ", ".join(KNOWN_CONNECTORS)
            raise ValueError(f"Unknown connector {name!r}. Known connectors: {known}.")
        if name not in names:
            names.append(name)
    return tuple(names)


def enabled_connectors(app_env: str, connectors: tuple[str, ...]) -> tuple[str, ...]:
    """APP_ENV=prod searches company systems. Anything else searches the log folder.

    An explicit CONNECTORS list replaces that default, so a company can turn
    systems off without changing the code.
    """
    if connectors:
        return connectors
    if app_env == "prod":
        return PRODUCTION_CONNECTORS
    return ("local_logs",)


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
    app_env: str = "local"
    connectors: tuple[str, ...] = ()
    cloudwatch_log_group_prefix: str = ""
    cloudwatch_log_groups: str = ""
    cloudwatch_lookback_minutes: int = 60
    datadog_site: str = "datadoghq.com"
    datadog_api_key: str = ""
    datadog_app_key: str = ""
    datadog_service_tag: str = "service"
    datadog_lookback_minutes: int = 60
    loki_url: str = ""
    loki_token: str = ""
    loki_label: str = "service"
    loki_lookback_minutes: int = 60
    github_api_url: str = "https://api.github.com"
    github_token: str = ""
    github_org: str = ""
    github_repos: str = ""
    github_lookback_hours: int = 24

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
        app_env = _env("APP_ENV", "local").lower()
        if app_env not in {"local", "prod"}:
            raise ValueError("APP_ENV must be 'local' or 'prod', " f"got {app_env!r}")
        connectors = parse_connectors(_env("CONNECTORS", ""))
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
            app_env=app_env,
            connectors=connectors,
            cloudwatch_log_group_prefix=_env("CLOUDWATCH_LOG_GROUP_PREFIX", ""),
            cloudwatch_log_groups=_env("CLOUDWATCH_LOG_GROUPS", ""),
            cloudwatch_lookback_minutes=_int_env(
                "CLOUDWATCH_LOOKBACK_MINUTES", 60, 1, 1440
            ),
            datadog_site=_env("DATADOG_SITE", "datadoghq.com"),
            datadog_api_key=_env("DATADOG_API_KEY", ""),
            datadog_app_key=_env("DATADOG_APP_KEY", ""),
            datadog_service_tag=_env("DATADOG_SERVICE_TAG", "service"),
            datadog_lookback_minutes=_int_env("DATADOG_LOOKBACK_MINUTES", 60, 1, 1440),
            loki_url=_env("LOKI_URL", ""),
            loki_token=_env("LOKI_TOKEN", ""),
            loki_label=_env("LOKI_LABEL", "service"),
            loki_lookback_minutes=_int_env("LOKI_LOOKBACK_MINUTES", 60, 1, 1440),
            github_api_url=_env("GITHUB_API_URL", "https://api.github.com").rstrip("/"),
            github_token=_env("GITHUB_TOKEN", ""),
            github_org=_env("GITHUB_ORG", ""),
            github_repos=_env("GITHUB_REPOS", ""),
            github_lookback_hours=_int_env("GITHUB_LOOKBACK_HOURS", 24, 1, 168),
        )
