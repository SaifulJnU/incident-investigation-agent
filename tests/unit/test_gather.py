from pathlib import Path

from incident_investigation_agent.core.config import Settings
from incident_investigation_agent.services.gather import _combine, gather
from incident_investigation_agent.services.investigation import _note_prompt


def test_local_searches_run_together_and_keep_hits():
    settings = _settings(Path("examples/logs"), connectors=("local_logs",))
    batch = gather(settings, "checkout-api")
    assert "search_logs timeout:" in batch.text
    assert "search_logs 500:" in batch.text
    summaries = [item.summary for item in batch.findings]
    assert any("vault" in line for line in summaries)
    assert any("status=500" in line for line in summaries)
    assert all(item.kind == "log" for item in batch.findings)
    assert len(summaries) == len(set(summaries))


def test_a_matching_line_that_says_must_be_is_kept(tmp_path):
    service = tmp_path / "checkout-api"
    service.mkdir()
    (service / "api.log").write_text(
        "ERROR timeout: value must be an integer\n",
        encoding="utf-8",
    )
    settings = _settings(tmp_path, connectors=("local_logs",))
    batch = gather(settings, "checkout-api")
    assert any("must be" in item.summary for item in batch.findings)


def test_empty_datadog_and_loki_searches_are_not_stored():
    batch = _combine(
        [
            (
                "search_datadog",
                "timeout",
                "No Datadog logs matched 'timeout' for service:checkout-api during the last 60 minutes.",
            ),
            (
                "search_loki",
                "500",
                "No Loki lines matched '500' for service=checkout-api during the last 60 minutes.",
            ),
            (
                "search_cloudwatch",
                "timeout",
                "checkout-api: ERROR timeout: value must be an integer",
            ),
        ]
    )
    summaries = [item.summary for item in batch.findings]
    assert summaries == ["checkout-api: ERROR timeout: value must be an integer"]


def test_words_from_the_case_are_searched_too(tmp_path):
    service = tmp_path / "checkout-api"
    service.mkdir()
    (service / "api.log").write_text(
        "ERROR disk full on /data\nINFO request status=200\n",
        encoding="utf-8",
    )
    settings = _settings(tmp_path, connectors=("local_logs",))
    hint = "Checkout errors after the deploy. The disk filled on the data volume."
    batch = gather(settings, "checkout-api", hint)
    assert "search_logs timeout:" in batch.text
    assert "search_logs disk:" in batch.text
    assert "search_logs deploy:" in batch.text
    assert "search_logs checkout:" not in batch.text
    assert "search_logs errors:" not in batch.text
    assert any("disk full" in item.summary for item in batch.findings)
    missed = gather(settings, "checkout-api")
    assert missed.findings == ()


def test_a_miss_is_reported_and_not_stored():
    settings = _settings(Path("examples/logs"), connectors=("local_logs",))
    batch = gather(settings, "payments-api")
    assert "does not exist" in batch.text or "No lines matched" in batch.text or "Log directory" in batch.text
    assert batch.findings == ()


def test_note_prompt_drops_the_tool_instruction():
    prompt = "Incident: Checkout\nStart by calling search_logs. Do not write the incident note."
    note = _note_prompt(prompt, "search_logs timeout:\napi.log:3: vault timeout")
    assert "Start by calling search_logs" not in note
    assert "vault timeout" in note
    assert "Write the incident note" in note


def _settings(log_dir: Path, connectors: tuple[str, ...]) -> Settings:
    return Settings(
        model_provider="ollama",
        ollama_host="http://localhost:11434",
        ollama_model="llama3.1",
        bedrock_model_id="test-model",
        aws_region="us-west-2",
        log_dir=log_dir,
        case_dir=Path(".case"),
        database_url="sqlite+pysqlite://",
        app_env="local",
        connectors=connectors,
    )
