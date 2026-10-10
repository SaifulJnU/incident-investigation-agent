from pathlib import Path

from incident_investigation_agent.core.config import Settings
from incident_investigation_agent.services.gather import Finding, SearchBatch, _combine, gather
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


def test_a_timed_out_line_is_kept_with_the_timeout_search():
    settings = _settings(Path("examples/logs"), connectors=("local_logs",))
    batch = gather(settings, "checkout-api")
    assert "search_logs timed out:" in batch.text
    assert any("timed out" in item.summary and "vault.internal" in item.summary for item in batch.findings)


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


def test_deployed_in_the_case_finds_a_line_that_says_deploy(tmp_path):
    service = tmp_path / "checkout-api"
    service.mkdir()
    (service / "api.log").write_text("INFO deploy finished\n", encoding="utf-8")
    settings = _settings(tmp_path, connectors=("local_logs",))
    hint = "A posted change was deployed."
    batch = gather(settings, "checkout-api", hint)
    assert "search_logs deploy:" in batch.text
    assert "search_logs deployed:" not in batch.text
    assert "search_logs posted:" in batch.text
    assert "search_logs post:" not in batch.text
    assert any("deploy finished" in item.summary for item in batch.findings)


def test_a_version_named_after_other_words_is_still_searched(tmp_path):
    service = tmp_path / "checkout-api"
    service.mkdir()
    (service / "api.log").write_text(
        "INFO deploy version=1.42.0\n",
        encoding="utf-8",
    )
    settings = _settings(tmp_path, connectors=("local_logs",))
    hint = "The error rate climbed after the rollout. Catalog still looks healthy. Version 1.42.0."
    batch = gather(settings, "checkout-api", hint)
    assert "search_logs rate:" in batch.text
    assert "search_logs 1.42.0:" in batch.text
    assert any("version=1.42.0" in item.summary for item in batch.findings)
    without = gather(settings, "checkout-api", "The error rate climbed after the rollout.")
    assert without.findings == ()


def test_a_status_code_named_after_other_words_is_still_searched(tmp_path):
    service = tmp_path / "checkout-api"
    service.mkdir()
    (service / "api.log").write_text("ERROR upstream status=503\n", encoding="utf-8")
    settings = _settings(tmp_path, connectors=("local_logs",))
    hint = "The error rate climbed after the rollout. Catalog still looks healthy. HTTP 503s."
    batch = gather(settings, "checkout-api", hint)
    assert "search_logs 503:" in batch.text
    assert "search_logs 503s:" not in batch.text
    assert batch.text.count("search_logs 500:") == 1
    assert any("status=503" in item.summary for item in batch.findings)
    without = gather(settings, "checkout-api", "The error rate climbed after the rollout.")
    assert without.findings == ()


def test_a_miss_is_reported_and_not_stored():
    settings = _settings(Path("examples/logs"), connectors=("local_logs",))
    batch = gather(settings, "payments-api")
    assert "does not exist" in batch.text or "No lines matched" in batch.text or "Log directory" in batch.text
    assert batch.findings == ()


def test_a_log_line_that_says_search_failed_is_kept():
    batch = _combine(
        [
            (
                "search_datadog",
                "timeout",
                "datadog service:checkout-api: ERROR payment search failed: handler returned no body",
            ),
            ("search_datadog", "500", "Datadog search failed: HTTP 401."),
            (
                "search_loki",
                "timeout",
                "No Loki lines matched 'timeout' for service=checkout-api during the last 60 minutes.",
            ),
        ]
    )
    summaries = [item.summary for item in batch.findings]
    assert summaries == [
        "datadog service:checkout-api: ERROR payment search failed: handler returned no body"
    ]
    assert batch.unchecked == ("Datadog search failed: HTTP 401.",)
    assert batch.misses == ("search_loki timeout",)


def test_note_prompt_leads_with_each_match_once():
    prompt = "Incident: Checkout\nStart by calling search_logs. Do not write the incident note."
    batch = SearchBatch(
        "search_logs timeout:\napi.log:3: vault timeout",
        (
            Finding("log", "api.log:3: vault timeout status=500", "api.log"),
            Finding("log", "api.log:4: vault connection timed out", "api.log"),
        ),
        misses=("search_logs climbed",),
        unchecked=("CloudWatch is not configured. Set CLOUDWATCH_LOG_GROUP_PREFIX.",),
    )
    note = _note_prompt(prompt, batch)
    assert "Start by calling search_logs" not in note
    assert note.count("vault timeout") == 1
    assert "api.log:4: vault connection timed out" in note
    assert note.index("vault timeout") < note.index("CloudWatch is not configured")
    assert note.index("CloudWatch is not configured") < note.index("No match for search_logs climbed.")
    assert note.endswith("Write the incident note from these lines.")


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
