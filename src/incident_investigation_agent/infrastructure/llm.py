"""Select Amazon Bedrock or a local Ollama model. The agent code stays the same."""

from __future__ import annotations

from incident_investigation_agent.core.config import Settings


def build_model(settings: Settings, max_tokens: int | None = None):
    if settings.model_provider == "ollama":
        from strands.models.ollama import OllamaModel

        config = {
            "host": settings.ollama_host,
            "model_id": settings.ollama_model,
            "temperature": 0,
        }
        if max_tokens is not None:
            config["max_tokens"] = max_tokens
        return OllamaModel(**config)

    from strands.models.bedrock import BedrockModel

    config = {
        "model_id": settings.bedrock_model_id,
        "region_name": settings.aws_region,
    }
    if max_tokens is not None:
        config["max_tokens"] = max_tokens
    return BedrockModel(**config)
