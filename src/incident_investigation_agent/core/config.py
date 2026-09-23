"""Runtime settings. Production defaults to Amazon Bedrock; local uses Ollama."""

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
class Settings:
    model_provider: str
    ollama_host: str
    ollama_model: str
    bedrock_model_id: str
    aws_region: str
    log_dir: Path
    case_dir: Path
    database_url: str

    @classmethod
    def from_env(cls) -> Settings:
        provider = _env("MODEL_PROVIDER", "bedrock").lower()
        if provider not in {"bedrock", "ollama"}:
            raise ValueError(
                "MODEL_PROVIDER must be 'bedrock' or 'ollama', "
                f"got {provider!r}"
            )
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
        )
