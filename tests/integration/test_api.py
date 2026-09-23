import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from incident_investigation_agent.api.app import create_app
from incident_investigation_agent.core.config import Settings, parse_dev_users
from incident_investigation_agent.db.models import Base


def _settings() -> Settings:
    return Settings(
        model_provider="ollama",
        ollama_host="http://localhost:11434",
        ollama_model="llama3.1",
        bedrock_model_id="test-model",
        aws_region="us-west-2",
        log_dir=__import__("pathlib").Path("examples/logs"),
        case_dir=__import__("pathlib").Path(".case"),
        database_url="sqlite+pysqlite://",
        auth_mode="dev",
        dev_auth_secret="test-dev-secret-value-32bytes-min",
        dev_users=parse_dev_users(
            "oncall|On-call engineer|checkout-api,payments-api|oncall-password;"
            "platform|Platform owner|*|platform-password"
        ),
    )


@pytest.fixture
def client():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    app = create_app(factory, settings=_settings())
    with TestClient(app) as test_client:
        yield test_client


def _auth(client, subject: str, password: str) -> dict[str, str]:
    response = client.post(
        "/api/auth/dev/token",
        json={"subject": subject, "password": password},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_health_stays_open(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["database"] == "ok"
    assert response.headers["x-request-id"]


def test_cases_require_a_token(client):
    response = client.get("/api/incidents")
    assert response.status_code == 401


def test_open_case_add_note_and_queue(client):
    headers = _auth(client, "oncall", "oncall-password")
    created = client.post(
        "/api/incidents",
        headers=headers,
        json={
            "title": "Checkout errors",
            "service": "checkout-api",
            "severity": "sev1",
            "summary": "POST /checkout returns 500 after the deploy.",
            "started_at": "2026-09-22T14:02:00Z",
        },
    )
    assert created.status_code == 201
    assert created.json()["opened_by"] == "oncall"
    assert created.json()["opened_by_name"] == "On-call engineer"
    incident_id = created.json()["id"]

    noted = client.post(
        f"/api/incidents/{incident_id}/evidence",
        headers=headers,
        json={"kind": "timeline", "summary": "payments-api 1.42.0 deployed"},
    )
    assert noted.status_code == 201
    assert noted.json()["evidence"][0]["source"] == "oncall"

    queued = client.post(f"/api/incidents/{incident_id}/investigate", headers=headers)
    assert queued.status_code == 202
    assert queued.json()["status"] == "queued"
    assert queued.json()["requested_by"] == "oncall"
    assert queued.json()["requested_by_name"] == "On-call engineer"

    again = client.post(f"/api/incidents/{incident_id}/investigate", headers=headers)
    assert again.status_code == 409


def test_on_call_cannot_open_or_read_another_service(client):
    oncall = _auth(client, "oncall", "oncall-password")
    denied = client.post(
        "/api/incidents",
        headers=oncall,
        json={
            "title": "Catalog latency",
            "service": "catalog-api",
            "severity": "sev3",
            "summary": "p95 climbed for ten minutes.",
        },
    )
    assert denied.status_code == 403

    platform = _auth(client, "platform", "platform-password")
    created = client.post(
        "/api/incidents",
        headers=platform,
        json={
            "title": "Catalog latency",
            "service": "catalog-api",
            "severity": "sev3",
            "summary": "p95 climbed for ten minutes.",
        },
    )
    incident_id = created.json()["id"]
    hidden = client.get(f"/api/incidents/{incident_id}", headers=oncall)
    assert hidden.status_code == 404
    listed = client.get("/api/incidents", headers=oncall)
    assert listed.json() == []


def test_rejects_blank_title(client):
    headers = _auth(client, "oncall", "oncall-password")
    response = client.post(
        "/api/incidents",
        headers=headers,
        json={
            "title": "   ",
            "service": "checkout-api",
            "severity": "sev2",
            "summary": "Latency climbed.",
        },
    )
    assert response.status_code == 422


def test_mark_mitigated(client):
    headers = _auth(client, "oncall", "oncall-password")
    created = client.post(
        "/api/incidents",
        headers=headers,
        json={
            "title": "Checkout errors",
            "service": "checkout-api",
            "severity": "sev1",
            "summary": "POST /checkout returns 500.",
        },
    )
    incident_id = created.json()["id"]
    patched = client.patch(
        f"/api/incidents/{incident_id}",
        headers=headers,
        json={"status": "mitigated"},
    )
    assert patched.status_code == 200
    assert patched.json()["status"] == "mitigated"
    assert patched.json()["mitigated_by_name"] == "On-call engineer"
    listed = client.get("/api/incidents", headers=headers)
    assert listed.json()[0]["status"] == "mitigated"
    mitigated = client.get("/api/incidents?status=mitigated", headers=headers)
    assert len(mitigated.json()) == 1
    resolved = client.get("/api/incidents?status=resolved", headers=headers)
    assert resolved.json() == []
    totals = client.get("/api/incidents/counts", headers=headers)
    assert totals.json()["mitigated"] == 1
    assert totals.json()["all"] == 1


def test_dev_sign_in_rejects_a_wrong_password(client):
    response = client.post(
        "/api/auth/dev/token",
        json={"subject": "oncall", "password": "nope"},
    )
    assert response.status_code == 401
