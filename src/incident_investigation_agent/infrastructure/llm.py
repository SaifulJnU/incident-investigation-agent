"""Select Amazon Bedrock or a local Ollama model. The agent code stays the same."""

from __future__ import annotations

from incident_investigation_agent.core.config import Settings


def build_model(settings: Settings):
    if settings.model_provider == "ollama":
        from strands.models.ollama import OllamaModel

        return OllamaModel(
            host=settings.ollama_host,
            model_id=settings.ollama_model,
            temperature=0,
        )

    from strands.models.bedrock import BedrockModel

    return BedrockModel(
        model_id=settings.bedrock_model_id,
        region_name=settings.aws_region,
    )
