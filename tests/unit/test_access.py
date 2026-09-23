import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from incident_investigation_agent.core.config import DevUser, Settings
from incident_investigation_agent.domain.access import Principal
from incident_investigation_agent.infrastructure import auth as auth_module
from incident_investigation_agent.infrastructure.auth import (
    AuthError,
    issue_dev_token,
    verify_access_token,
)


def test_service_scope_is_closed():
    engineer = Principal(
        subject="ada",
        name="Ada",
        services=frozenset({"checkout-api", "payments-api"}),
        roles=frozenset(),
    )
    assert engineer.may_access("checkout-api")
    assert not engineer.may_access("catalog-api")
    assert engineer.list_scope() == frozenset({"checkout-api", "payments-api"})


def test_admin_role_may_access_every_service():
    admin = Principal(
        subject="platform",
        name="Platform",
        services=frozenset(),
        roles=frozenset({"incident-admin"}),
    )
    assert admin.may_access("catalog-api")
    assert admin.list_scope() is None


def _dev_settings() -> Settings:
    return Settings(
        model_provider="ollama",
        ollama_host="http://localhost:11434",
        ollama_model="llama3.1",
        bedrock_model_id="test",
        aws_region="us-west-2",
        log_dir=__import__("pathlib").Path("examples/logs"),
        case_dir=__import__("pathlib").Path(".case"),
        database_url="sqlite+pysqlite://",
        auth_mode="dev",
        dev_auth_secret="test-dev-secret-value-32bytes-min",
        dev_users=(
            DevUser(
                subject="oncall",
                name="On-call",
                services=frozenset({"checkout-api"}),
                password="oncall-password",
            ),
        ),
    )


def test_dev_token_round_trip():
    settings = _dev_settings()
    issued = issue_dev_token(settings, settings.dev_users[0])
    principal = verify_access_token(settings, issued.access_token)
    assert principal.subject == "oncall"
    assert principal.may_access("checkout-api")
    assert not principal.may_access("billing-api")


def test_oidc_token_is_accepted_and_scoped(monkeypatch):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    token = jwt.encode(
        {
            "iss": "https://login.example.com",
            "aud": "case-file",
            "sub": "ada",
            "name": "Ada",
            "services": ["checkout-api", "payments-api"],
            "roles": [],
            "exp": int(time.time()) + 300,
        },
        key,
        algorithm="RS256",
        headers={"kid": "test"},
    )
    settings = Settings(
        model_provider="bedrock",
        ollama_host="http://localhost:11434",
        ollama_model="llama3.1",
        bedrock_model_id="test",
        aws_region="us-west-2",
        log_dir=__import__("pathlib").Path("examples/logs"),
        case_dir=__import__("pathlib").Path(".case"),
        database_url="sqlite+pysqlite://",
        auth_mode="oidc",
        oidc_issuer="https://login.example.com",
        oidc_audience="case-file",
        oidc_jwks_url="https://login.example.com/jwks",
    )

    class _Key:
        def __init__(self, public_key):
            self.key = public_key

    class _Client:
        def get_signing_key_from_jwt(self, _token):
            return _Key(key.public_key())

    monkeypatch.setitem(auth_module._jwks_clients, settings.oidc_jwks_url, _Client())
    principal = verify_access_token(settings, token)
    assert principal.subject == "ada"
    assert principal.may_access("payments-api")
    assert not principal.may_access("catalog-api")


def test_rejects_a_dev_token_when_oidc_is_required(monkeypatch):
    dev = _dev_settings()
    issued = issue_dev_token(dev, dev.dev_users[0])
    oidc = Settings(
        model_provider="bedrock",
        ollama_host="http://localhost:11434",
        ollama_model="llama3.1",
        bedrock_model_id="test",
        aws_region="us-west-2",
        log_dir=__import__("pathlib").Path("examples/logs"),
        case_dir=__import__("pathlib").Path(".case"),
        database_url="sqlite+pysqlite://",
        auth_mode="oidc",
        oidc_issuer="https://login.example.com",
        oidc_audience="case-file",
        oidc_jwks_url="https://login.example.com/jwks",
    )

    class _Client:
        def get_signing_key_from_jwt(self, _token):
            raise jwt.InvalidTokenError("not an identity-provider token")

    monkeypatch.setitem(auth_module._jwks_clients, "https://login.example.com/jwks", _Client())
    with pytest.raises(AuthError):
        verify_access_token(oidc, issued.access_token)
