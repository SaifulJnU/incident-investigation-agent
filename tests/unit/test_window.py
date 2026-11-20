from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

from incident_investigation_agent.infrastructure.connectors.cloudwatch import search_cloudwatch_logs
from incident_investigation_agent.infrastructure.connectors.datadog import search_datadog_logs
from incident_investigation_agent.infrastructure.connectors.github import list_commits
from incident_investigation_agent.infrastructure.connectors.loki import search_loki_logs
from incident_investigation_agent.infrastructure.connectors.window import epoch_ms, epoch_ns, search_span
from incident_investigation_agent.services.gather import gather
from incident_investigation_agent.services.report import BRIEF_TAIL, IncidentBrief, case_started_at, investigation_prompt
from incident_investigation_agent.core.config import Settings
from pathlib import Path


NOW = datetime(2026, 9, 22, 16, 0, tzinfo=timezone.utc)
INSIDE = datetime(2026, 9, 22, 15, 20, tzinfo=timezone.utc)
OLDER = datetime(2026, 9, 22, 14, 2, tzinfo=timezone.utc)


def _settings(**overrides) -> Settings:
    values = dict(
        model_provider="ollama",
        ollama_host="http://localhost:11434",
        ollama_model="llama3.1",
        bedrock_model_id="test-model",
        aws_region="us-west-2",
        log_dir=Path("examples/logs"),
        case_dir=Path(".case"),
        database_url="sqlite+pysqlite://",
        app_env="prod",
    )
    values.update(overrides)
    return Settings(**values)


def _freeze(monkeypatch):
    monkeypatch.setattr(
        "incident_investigation_agent.infrastructure.connectors.window.utcnow",
        lambda: NOW,
    )


def test_a_start_inside_the_lookback_keeps_the_span_ending_now():
    start, end, anchored = search_span(INSIDE, timedelta(minutes=60), now=NOW)
    assert anchored is False
    assert start == NOW - timedelta(minutes=60)
    assert end == NOW


def test_a_start_older_than_the_lookback_moves_the_span():
    start, end, anchored = search_span(OLDER, timedelta(minutes=60), now=NOW)
    assert anchored is True
    assert start == OLDER
    assert end == OLDER + timedelta(minutes=60)


def test_a_missing_start_keeps_the_span_ending_now():
    start, end, anchored = search_span(None, timedelta(hours=24), now=NOW)
    assert anchored is False
    assert end == NOW
    assert start == NOW - timedelta(hours=24)


def test_the_brief_start_is_read_and_a_later_line_is_not():
    prompt = investigation_prompt(
        IncidentBrief(
            title="Checkout errors",
            service="checkout-api",
            severity="sev1",
            summary="POST /checkout returns 500.",
            started_at=OLDER,
        ),
        [],
    )
    assert case_started_at(prompt) == OLDER
    trailed = f"{prompt}\nStarted: 2026-01-01T00:00:00+00:00"
    assert BRIEF_TAIL in trailed
    assert case_started_at(trailed) == OLDER
    assert case_started_at("checkout 500s started at 14:02") is None


def test_cloudwatch_searches_from_an_older_case_start(monkeypatch):
    _freeze(monkeypatch)
    seen = {}

    class _Client:
        def filter_log_events(self, **kwargs):
            seen.update(kwargs)
            return {"events": []}

    monkeypatch.setattr(
        "incident_investigation_agent.infrastructure.connectors.cloudwatch.logs_client",
        lambda region, endpoint_url="", timeout=15: _Client(),
    )
    settings = _settings(cloudwatch_log_group_prefix="/aws/ecs/")
    result = search_cloudwatch_logs(settings, "checkout-api", "timeout", 5, OLDER)
    assert seen["startTime"] == epoch_ms(OLDER)
    assert seen["endTime"] == epoch_ms(OLDER + timedelta(minutes=60))
    assert "60 minutes from 2026-09-22T14:02:00Z" in result

    seen.clear()
    fresh = search_cloudwatch_logs(settings, "checkout-api", "timeout", 5, INSIDE)
    assert seen["startTime"] == epoch_ms(NOW - timedelta(minutes=60))
    assert "endTime" not in seen
    assert "the last 60 minutes" in fresh


def test_datadog_and_loki_use_the_same_moved_span(monkeypatch):
    _freeze(monkeypatch)
    seen = {}

    def fake_datadog(url, method="GET", headers=None, payload=None, timeout=15):
        seen["datadog"] = payload
        return {"data": []}

    def fake_loki(url, method="GET", headers=None, payload=None, timeout=15):
        seen["loki"] = parse_qs(urlparse(url).query)
        return {"data": {"result": []}}

    monkeypatch.setattr(
        "incident_investigation_agent.infrastructure.connectors.datadog.request_json",
        fake_datadog,
    )
    monkeypatch.setattr(
        "incident_investigation_agent.infrastructure.connectors.loki.request_json",
        fake_loki,
    )
    settings = _settings(
        datadog_api_key="secret-key",
        datadog_app_key="secret-app",
        loki_url="https://loki.example.com",
    )
    datadog = search_datadog_logs(settings, "checkout-api", "timeout", 5, OLDER)
    loki = search_loki_logs(settings, "checkout-api", "timeout", 5, OLDER)
    assert seen["datadog"]["filter"]["from"] == "2026-09-22T14:02:00Z"
    assert seen["datadog"]["filter"]["to"] == "2026-09-22T15:02:00Z"
    assert seen["loki"]["start"] == [str(epoch_ns(OLDER))]
    assert seen["loki"]["end"] == [str(epoch_ns(OLDER + timedelta(minutes=60)))]
    assert "60 minutes from 2026-09-22T14:02:00Z" in datadog
    assert "60 minutes from 2026-09-22T14:02:00Z" in loki


def test_github_stops_at_the_end_of_the_moved_span(monkeypatch):
    _freeze(monkeypatch)
    seen = {}

    def fake(url, method="GET", headers=None, payload=None, timeout=15):
        seen["url"] = url
        return []

    monkeypatch.setattr(
        "incident_investigation_agent.infrastructure.connectors.github.request_json",
        fake,
    )
    settings = _settings(github_token="gh-secret", github_org="acme", github_lookback_hours=24)
    opened = datetime(2026, 9, 21, 14, 2, tzinfo=timezone.utc)
    result = list_commits(settings, "checkout-api", started_at=opened)
    query = parse_qs(urlparse(seen["url"]).query)
    assert query["since"] == ["2026-09-21T14:02:00Z"]
    assert query["until"] == ["2026-09-22T14:02:00Z"]
    assert "24 hours from 2026-09-21T14:02:00Z" in result

    list_commits(settings, "checkout-api", started_at=NOW - timedelta(hours=2))
    recent = parse_qs(urlparse(seen["url"]).query)
    assert "until" not in recent


def test_gather_passes_the_case_start_through(monkeypatch):
    seen = {}

    def fake(_settings, _service, _query, _limit, started_at=None):
        seen["started"] = started_at
        return "No CloudWatch events matched 'timeout' in group during the last 60 minutes."

    monkeypatch.setattr(
        "incident_investigation_agent.services.gather.cloudwatch.search_cloudwatch_logs",
        fake,
    )
    settings = _settings(app_env="local", connectors=("cloudwatch",))
    gather(settings, "checkout-api", "", OLDER)
    assert seen["started"] == OLDER
