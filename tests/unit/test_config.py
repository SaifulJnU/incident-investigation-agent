import pytest

from incident_investigation_agent.core.config import Settings


def test_defaults_to_bedrock(monkeypatch):
    monkeypatch.delenv("MODEL_PROVIDER", raising=False)
    monkeypatch.delenv("AUTH_MODE", raising=False)
    monkeypatch.setenv("OIDC_ISSUER", "https://login.example.com")
    monkeypatch.setenv("OIDC_AUDIENCE", "case-file")
    settings = Settings.from_env()
    assert settings.model_provider == "bedrock"
    assert settings.auth_mode == "oidc"
    assert settings.bedrock_model_id == "global.anthropic.claude-sonnet-4-6"
    assert settings.ollama_model == "llama3.1"


def test_oidc_requires_an_issuer(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "oidc")
    monkeypatch.delenv("OIDC_ISSUER", raising=False)
    with pytest.raises(ValueError, match="OIDC_ISSUER"):
        Settings.from_env()


def test_ollama_provider_and_model_override(monkeypatch):
    monkeypatch.setenv("MODEL_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_MODEL", "qwen2.5:7b")
    monkeypatch.setenv("OLLAMA_HOST", "http://127.0.0.1:11434")
    settings = Settings.from_env()
    assert settings.model_provider == "ollama"
    assert settings.ollama_model == "qwen2.5:7b"
    assert settings.ollama_host == "http://127.0.0.1:11434"


def test_rejects_unknown_provider(monkeypatch):
    monkeypatch.setenv("MODEL_PROVIDER", "openai")
    with pytest.raises(ValueError, match="MODEL_PROVIDER"):
        Settings.from_env()
