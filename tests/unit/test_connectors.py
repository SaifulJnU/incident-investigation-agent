from pathlib import Path
from urllib.parse import parse_qs, urlparse

from incident_investigation_agent.core.config import Settings, enabled_connectors
from incident_investigation_agent.infrastructure.connectors.cloudwatch import search_cloudwatch_logs
from incident_investigation_agent.infrastructure.connectors.datadog import search_datadog_logs
from incident_investigation_agent.infrastructure.connectors.github import list_commits
from incident_investigation_agent.infrastructure.connectors.loki import search_loki_logs
from incident_investigation_agent.infrastructure.connectors.local_logs import search_local_logs
from incident_investigation_agent.infrastructure.connectors.registry import connector_tools


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
    )
    values.update(overrides)
    return Settings(**values)


def test_local_search_stays_inside_the_service(tmp_path):
    (tmp_path / "checkout-api").mkdir()
    (tmp_path / "checkout-api" / "api.log").write_text("ERROR vault timeout\n", encoding="utf-8")
    (tmp_path / "catalog-api").mkdir()
    (tmp_path / "catalog-api" / "api.log").write_text("ERROR catalog secret\n", encoding="utf-8")
    settings = _settings(log_dir=tmp_path, app_env="local")
    result = search_local_logs(settings, "checkout-api", "secret", 10)
    assert "catalog secret" not in result
    assert result.startswith("No lines matched")


def test_prod_enables_company_connectors():
    names = enabled_connectors("prod", ())
    assert names == ("cloudwatch", "datadog", "loki", "github")
    tools = connector_tools(_settings(app_env="prod"), "checkout-api")
    assert [tool.tool_name for tool in tools] == [
        "search_cloudwatch",
        "search_datadog",
        "search_loki",
        "list_recent_commits",
    ]


def test_connectors_override_the_env_default():
    assert enabled_connectors("prod", ("github",)) == ("github",)
    assert enabled_connectors("local", ("cloudwatch",)) == ("cloudwatch",)


def test_cloudwatch_reports_a_missing_log_group():
    result = search_cloudwatch_logs(_settings(app_env="prod"), "checkout-api", "timeout", 5)
    assert "CLOUDWATCH_LOG_GROUP_PREFIX" in result


def test_cloudwatch_reads_the_mapped_group(monkeypatch):
    class _Client:
        def filter_log_events(self, **kwargs):
            assert kwargs["logGroupName"] == "/aws/ecs/checkout-api"
            assert kwargs["filterPattern"] == "timeout"
            return {"events": [{"message": "vault timeout"}]}

    monkeypatch.setattr(
        "incident_investigation_agent.infrastructure.connectors.cloudwatch.logs_client",
        lambda region, endpoint_url="": _Client(),
    )
    settings = _settings(app_env="prod", cloudwatch_log_group_prefix="/aws/ecs/")
    result = search_cloudwatch_logs(settings, "checkout-api", "timeout", 5)
    assert "vault timeout" in result
    assert "/aws/ecs/checkout-api" in result


def test_datadog_scopes_the_query_and_hides_the_key(monkeypatch):
    seen = {}

    def fake(url, method="GET", headers=None, payload=None, timeout=15):
        seen["url"] = url
        seen["payload"] = payload
        seen["key"] = headers["DD-API-KEY"]
        return {"data": [{"attributes": {"message": "vault timeout"}}]}

    monkeypatch.setattr(
        "incident_investigation_agent.infrastructure.connectors.datadog.request_json",
        fake,
    )
    settings = _settings(
        app_env="prod",
        datadog_api_key="secret-key",
        datadog_app_key="secret-app",
        datadog_site="datadoghq.eu",
    )
    result = search_datadog_logs(settings, "checkout-api", "timeout", 5)
    assert seen["url"] == "https://api.datadoghq.eu/api/v2/logs/events/search"
    assert seen["payload"]["filter"]["query"] == "service:checkout-api timeout"
    assert seen["key"] == "secret-key"
    assert "vault timeout" in result
    assert "secret-key" not in result


def test_datadog_names_the_missing_setting():
    result = search_datadog_logs(_settings(app_env="prod"), "checkout-api", "timeout", 5)
    assert result == "Datadog is not configured. Set DATADOG_API_KEY."


def test_loki_scopes_the_label(monkeypatch):
    seen = {}

    def fake(url, method="GET", headers=None, payload=None, timeout=15):
        seen["url"] = url
        seen["auth"] = headers.get("Authorization", "")
        return {"data": {"result": [{"values": [["1", "vault timeout"]]}]}}

    monkeypatch.setattr(
        "incident_investigation_agent.infrastructure.connectors.loki.request_json",
        fake,
    )
    settings = _settings(app_env="prod", loki_url="https://loki.example.com", loki_token="loki-secret")
    result = search_loki_logs(settings, "checkout-api", "timeout", 5)
    logql = parse_qs(urlparse(seen["url"]).query)["query"][0]
    assert logql == '{service="checkout-api"} |= "timeout"'
    assert "loki-secret" not in result
    assert "vault timeout" in result
    assert seen["auth"] == "Bearer loki-secret"


def test_github_uses_the_org_and_hides_the_token(monkeypatch):
    seen = {}

    def fake(url, method="GET", headers=None, payload=None, timeout=15):
        seen["url"] = url
        seen["auth"] = headers["Authorization"]
        return [{"sha": "abc1234def", "commit": {"message": "deploy payments", "author": {"date": "2026-09-23T12:00:00Z"}}}]

    monkeypatch.setattr(
        "incident_investigation_agent.infrastructure.connectors.github.request_json",
        fake,
    )
    settings = _settings(app_env="prod", github_token="gh-secret", github_org="acme")
    result = list_commits(settings, "checkout-api", 5)
    assert "/repos/acme/checkout-api/commits?" in seen["url"]
    assert seen["auth"] == "Bearer gh-secret"
    assert "deploy payments" in result
    assert "gh-secret" not in result


def test_github_names_the_missing_token():
    result = list_commits(_settings(app_env="prod", github_org="acme"), "checkout-api")
    assert result == "GitHub is not configured. Set GITHUB_TOKEN."
