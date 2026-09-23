import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from incident_investigation_agent.api.app import create_app
from incident_investigation_agent.schema import Base


@pytest.fixture
def client():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    app = create_app(factory)
    with TestClient(app) as test_client:
        yield test_client


def test_health(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["database"] == "ok"
    assert response.headers["x-request-id"]


def test_open_case_add_note_and_queue(client):
    created = client.post(
        "/api/incidents",
        json={
            "title": "Checkout errors",
            "service": "checkout-api",
            "severity": "sev1",
            "summary": "POST /checkout returns 500 after the deploy.",
            "started_at": "2026-09-22T14:02:00Z",
        },
    )
    assert created.status_code == 201
    incident_id = created.json()["id"]

    noted = client.post(
        f"/api/incidents/{incident_id}/evidence",
        json={"kind": "timeline", "summary": "payments-api 1.42.0 deployed"},
    )
    assert noted.status_code == 201
    assert noted.json()["evidence"][0]["source"] == "operator"

    queued = client.post(f"/api/incidents/{incident_id}/investigate")
    assert queued.status_code == 202
    assert queued.json()["status"] == "queued"

    again = client.post(f"/api/incidents/{incident_id}/investigate")
    assert again.status_code == 409


def test_rejects_blank_title(client):
    response = client.post(
        "/api/incidents",
        json={
            "title": "   ",
            "service": "checkout-api",
            "severity": "sev2",
            "summary": "Latency climbed.",
        },
    )
    assert response.status_code == 422


def test_mark_mitigated(client):
    created = client.post(
        "/api/incidents",
        json={
            "title": "Catalog latency",
            "service": "catalog-api",
            "severity": "sev3",
            "summary": "p95 climbed for ten minutes.",
        },
    )
    incident_id = created.json()["id"]
    patched = client.patch(f"/api/incidents/{incident_id}", json={"status": "mitigated"})
    assert patched.status_code == 200
    assert patched.json()["status"] == "mitigated"
    listed = client.get("/api/incidents")
    assert listed.json()[0]["status"] == "mitigated"
