import logging
import uuid
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from incident_investigation_agent.api.app import create_app
from incident_investigation_agent.core.config import Settings, parse_dev_users
from incident_investigation_agent.db.models import Base, InvestigationRun
from incident_investigation_agent.services.heartbeat import record_beat


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
    assert response.status_code == 503
    assert response.json() == {"status": "degraded", "database": "ok", "worker": "down"}
    assert response.headers["x-request-id"]


def test_liveness_stays_up_when_the_worker_is_down(client):
    live = client.get("/api/live")
    assert live.status_code == 200
    assert live.json() == {"status": "ok"}
    ready = client.get("/api/ready")
    assert ready.status_code == 200
    assert ready.json() == {"status": "ok", "database": "ok"}
    health = client.get("/api/health")
    assert health.status_code == 503
    assert health.json()["worker"] == "down"


def test_a_process_waiting_on_the_database_is_still_alive():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    app = create_app(factory, settings=_settings())
    with TestClient(app) as waiting:
        live = waiting.get("/api/live")
        assert live.status_code == 200
        assert live.json() == {"status": "ok"}
        ready = waiting.get("/api/ready")
        assert ready.status_code == 503
        assert ready.json() == {"status": "unavailable", "database": "down"}
        health = waiting.get("/api/health")
        assert health.status_code == 503
        assert health.json() == {"status": "degraded", "database": "down", "worker": "unknown"}


def test_metrics_names_an_empty_queue_without_a_token(client):
    response = client.get("/api/metrics")
    assert response.status_code == 200
    assert response.json() == {
        "queued": 0,
        "running": 0,
        "completed_last_hour": 0,
        "failed_last_hour": 0,
        "oldest_queued_seconds": None,
    }


def test_metrics_stays_unavailable_until_the_schema_can_be_read():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    app = create_app(factory, settings=_settings())
    with TestClient(app) as waiting:
        response = waiting.get("/api/metrics")
    assert response.status_code == 503
    assert response.json() == {"status": "unavailable", "database": "down"}
    assert "queued" not in response.json()


def test_health_is_ok_when_the_worker_has_beaten(client):
    factory = client.app.state.session_factory
    with factory() as session:
        record_beat(session)
        session.commit()

    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok", "worker": "ok"}


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
    assert noted.json()["evidence"][0]["source"] == "On-call engineer (oncall)"

    records: list[logging.LogRecord] = []

    class _Grab(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    api_log = logging.getLogger("incident_investigation_agent.api")
    handler = _Grab()
    api_log.addHandler(handler)
    api_log.setLevel(logging.INFO)
    try:
        queued = client.post(f"/api/incidents/{incident_id}/investigate", headers=headers)
    finally:
        api_log.removeHandler(handler)
    assert queued.status_code == 202
    assert queued.json()["status"] == "queued"
    assert queued.json()["requested_by"] == "oncall"
    assert queued.json()["requested_by_name"] == "On-call engineer"
    run_id = queued.json()["id"]
    assert any(
        record.getMessage() == f"investigation queued case={incident_id} run={run_id} service=checkout-api"
        for record in records
    )

    again = client.post(f"/api/incidents/{incident_id}/investigate", headers=headers)
    assert again.status_code == 409


def _open_case(client, headers, title: str) -> str:
    created = client.post(
        "/api/incidents",
        headers=headers,
        json={
            "title": title,
            "service": "checkout-api",
            "severity": "sev2",
            "summary": "POST /checkout returns 500.",
        },
    )
    assert created.status_code == 201
    return created.json()["id"]


def test_a_full_queue_refuses_another_investigate():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    app = create_app(factory, settings=replace(_settings(), max_queued_runs=1))
    with TestClient(app) as client:
        headers = _auth(client, "oncall", "oncall-password")
        first = _open_case(client, headers, "Checkout errors")
        queued = client.post(f"/api/incidents/{first}/investigate", headers=headers)
        assert queued.status_code == 202

        second = _open_case(client, headers, "Checkout latency")
        refused = client.post(f"/api/incidents/{second}/investigate", headers=headers)
        assert refused.status_code == 429
        assert refused.json()["detail"] == (
            "The investigation queue for this service is full. "
            "Wait for a run to start, then try again."
        )
        same_case = client.post(f"/api/incidents/{first}/investigate", headers=headers)
        assert same_case.status_code == 409

        with factory() as session:
            run = session.get(InvestigationRun, uuid.UUID(queued.json()["id"]))
            assert run is not None
            run.status = "running"
            session.commit()

        started = client.post(f"/api/incidents/{second}/investigate", headers=headers)
        assert started.status_code == 202


def test_a_full_service_queue_does_not_block_another_service():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    app = create_app(factory, settings=replace(_settings(), max_queued_runs=1))
    with TestClient(app) as client:
        headers = _auth(client, "oncall", "oncall-password")
        checkout = _open_case(client, headers, "Checkout errors")
        queued = client.post(f"/api/incidents/{checkout}/investigate", headers=headers)
        assert queued.status_code == 202

        payments = client.post(
            "/api/incidents",
            headers=headers,
            json={
                "title": "Payments timeout",
                "service": "payments-api",
                "severity": "sev2",
                "summary": "The vault timed out.",
            },
        )
        assert payments.status_code == 201
        other = client.post(
            f"/api/incidents/{payments.json()['id']}/investigate",
            headers=headers,
        )
        assert other.status_code == 202


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
    assert listed.json() == {"cases": [], "next_before": None, "next_before_id": None}


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
    assert listed.json()["cases"][0]["status"] == "mitigated"
    assert listed.json()["next_before"] is None
    mitigated = client.get("/api/incidents?status=mitigated", headers=headers)
    assert len(mitigated.json()["cases"]) == 1
    resolved = client.get("/api/incidents?status=resolved", headers=headers)
    assert resolved.json()["cases"] == []
    totals = client.get("/api/incidents/counts", headers=headers)
    assert totals.json()["mitigated"] == 1
    assert totals.json()["all"] == 1


def test_a_resolved_case_stays_closed(client):
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
    claimed = client.patch(
        f"/api/incidents/{incident_id}",
        headers=headers,
        json={"status": "investigating"},
    )
    assert claimed.status_code == 409
    mitigated = client.patch(
        f"/api/incidents/{incident_id}",
        headers=headers,
        json={"status": "mitigated"},
    )
    assert mitigated.status_code == 200
    again = client.patch(
        f"/api/incidents/{incident_id}",
        headers=headers,
        json={"status": "mitigated"},
    )
    assert again.status_code == 409
    assert again.json()["detail"] == "This case is already mitigated."
    resolved = client.patch(
        f"/api/incidents/{incident_id}",
        headers=headers,
        json={"status": "resolved"},
    )
    assert resolved.status_code == 200
    body = resolved.json()
    assert body["status"] == "resolved"
    assert body["mitigated_by_name"] == "On-call engineer"
    assert body["resolved_by_name"] == "On-call engineer"
    detail = client.get(f"/api/incidents/{incident_id}", headers=headers)
    changes = detail.json()["status_changes"]
    assert [item["to_status"] for item in changes] == ["open", "mitigated", "resolved"]
    assert [item["from_status"] for item in changes] == [None, "open", "mitigated"]
    assert [item["actor"] for item in changes] == ["oncall", "oncall", "oncall"]
    assert changes[0]["actor_name"] == "On-call engineer"
    for status in ("open", "investigating", "mitigated", "resolved"):
        refused = client.patch(
            f"/api/incidents/{incident_id}",
            headers=headers,
            json={"status": status},
        )
        assert refused.status_code == 409
        assert refused.json()["detail"] == "This case is resolved."


def test_the_case_list_returns_one_page_then_the_next(client, monkeypatch):
    monkeypatch.setattr(
        "incident_investigation_agent.api.routes.incidents.CASE_PAGE_SIZE",
        2,
    )
    headers = _auth(client, "oncall", "oncall-password")
    for title, started in (
        ("Oldest", "2026-09-22T12:00:00Z"),
        ("Same start A", "2026-09-22T13:00:00Z"),
        ("Same start B", "2026-09-22T13:00:00Z"),
        ("Newest", "2026-09-22T14:00:00Z"),
    ):
        created = client.post(
            "/api/incidents",
            headers=headers,
            json={
                "title": title,
                "service": "checkout-api",
                "severity": "sev2",
                "summary": "POST /checkout returns 500.",
                "started_at": started,
            },
        )
        assert created.status_code == 201

    first = client.get("/api/incidents", headers=headers)
    assert first.status_code == 200
    page = first.json()
    titles = [item["title"] for item in page["cases"]]
    assert titles[0] == "Newest"
    assert titles[1] in {"Same start A", "Same start B"}
    assert page["next_before_id"] == page["cases"][-1]["id"]

    second = client.get(
        "/api/incidents",
        headers=headers,
        params={"before": page["next_before"], "before_id": page["next_before_id"]},
    )
    assert second.status_code == 200
    follow = second.json()
    assert follow["next_before"] is None
    assert follow["next_before_id"] is None
    follow_titles = [item["title"] for item in follow["cases"]]
    assert "Oldest" in follow_titles
    assert set(titles + follow_titles) == {
        "Oldest",
        "Same start A",
        "Same start B",
        "Newest",
    }
    assert {item["id"] for item in page["cases"]}.isdisjoint(item["id"] for item in follow["cases"])


def test_a_page_cursor_needs_both_fields(client):
    headers = _auth(client, "oncall", "oncall-password")
    missing_id = client.get(
        "/api/incidents",
        headers=headers,
        params={"before": "2026-09-22T14:00:00Z"},
    )
    assert missing_id.status_code == 422
    missing_time = client.get(
        "/api/incidents",
        headers=headers,
        params={"before_id": "00000000-0000-0000-0000-000000000001"},
    )
    assert missing_time.status_code == 422


def test_dev_sign_in_rejects_a_wrong_password(client):
    response = client.post(
        "/api/auth/dev/token",
        json={"subject": "oncall", "password": "nope"},
    )
    assert response.status_code == 401
