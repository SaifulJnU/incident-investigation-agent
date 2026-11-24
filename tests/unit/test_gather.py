import time
from datetime import datetime, timezone
from pathlib import Path

from incident_investigation_agent.core.config import Settings
from incident_investigation_agent.services.gather import (
    FINDING_TEXT_LIMIT,
    Finding,
    SearchBatch,
    _combine,
    _follow_query,
    gather,
)
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
    assert batch.spans == ()
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


def test_a_hung_connector_fails_that_source_and_keeps_the_others(tmp_path, monkeypatch):
    def search(_settings, _service, query, _limit):
        if query == "timeout":
            time.sleep(8)
            return "api.log:1: should not be kept"
        return "api.log:1: ERROR status=500 disk"

    monkeypatch.setattr(
        "incident_investigation_agent.services.gather.local_logs.search_local_logs",
        search,
    )
    settings = _settings(tmp_path, connectors=("local_logs",), connector_timeout_seconds=1)
    started = time.perf_counter()
    batch = gather(settings, "checkout-api")
    elapsed = time.perf_counter() - started
    assert elapsed < 4
    assert any("status=500" in item.summary for item in batch.findings)
    assert "should not be kept" not in batch.text
    assert any("did not finish within 1 second" in line for line in batch.unchecked)
    assert all("should not be kept" not in item.summary for item in batch.findings)


def test_a_long_matching_line_keeps_its_start():
    short = "ERROR timeout: vault"
    exact = "E" * FINDING_TEXT_LIMIT
    long_line = "ERROR timeout: " + ("x" * FINDING_TEXT_LIMIT)
    batch = _combine(
        [
            (
                "search_logs",
                "timeout",
                "\n".join([short, exact, long_line, long_line + "more", long_line + "other"]),
            )
        ]
    )
    summaries = [item.summary for item in batch.findings]
    assert short in summaries
    assert exact in summaries
    clipped = [item for item in summaries if item.endswith("...")]
    assert clipped == [long_line[: FINDING_TEXT_LIMIT - 3].rstrip() + "..."]
    assert all(len(item) <= FINDING_TEXT_LIMIT for item in summaries)


def test_one_word_from_the_first_lines_is_searched_before_the_note(tmp_path):
    service = tmp_path / "checkout-api"
    service.mkdir()
    (service / "api.log").write_text(
        "ERROR timeout from the certificate store\nINFO certificate expired\n",
        encoding="utf-8",
    )
    settings = _settings(tmp_path, connectors=("local_logs",))
    batch = gather(settings, "checkout-api")
    assert "search_logs timeout:" in batch.text
    assert "search_logs certificate:" in batch.text
    assert any("certificate expired" in item.summary for item in batch.findings)


def test_the_follow_up_reads_the_message_not_the_connector_label():
    queries = ("timeout", "timed out", "500")
    assert _follow_query(
        (
            Finding(
                "log",
                "datadog service:checkout-api: ERROR timeout from the certificate store",
                "search_datadog",
            ),
        ),
        queries,
        "checkout-api",
    ) == "certificate"
    assert _follow_query(
        (
            Finding(
                "log",
                "loki service=checkout-api: ERROR timeout from the vault",
                "search_loki",
            ),
        ),
        queries,
        "checkout-api",
    ) == "vault"
    assert _follow_query(
        (
            Finding(
                "log",
                "/aws/lambda/checkout-api: ERROR timeout from the vault",
                "search_cloudwatch",
            ),
        ),
        queries,
        "checkout-api",
    ) == "vault"
    assert _follow_query(
        (
            Finding(
                "change",
                "acme/checkout-api abc1234 2026-09-23T12:00:00Z the certificate expired",
                "list_recent_commits",
            ),
        ),
        queries,
        "checkout-api",
    ) == "certificate"


def test_the_follow_up_still_prefers_a_code_in_the_message():
    assert _follow_query(
        (
            Finding(
                "log",
                "datadog service:checkout-api: ERROR timeout status=503",
                "search_datadog",
            ),
        ),
        ("timeout", "timed out", "500"),
        "checkout-api",
    ) == "503"


def test_a_status_code_in_the_first_lines_is_the_follow_up(tmp_path):
    service = tmp_path / "checkout-api"
    service.mkdir()
    (service / "api.log").write_text(
        "ERROR timeout status=503\nINFO gateway returned 503 after the certificate check\n",
        encoding="utf-8",
    )
    settings = _settings(tmp_path, connectors=("local_logs",))
    batch = gather(settings, "checkout-api")
    assert "search_logs 503:" in batch.text
    assert "search_logs gateway:" not in batch.text
    assert any("status=503" in item.summary for item in batch.findings)


def test_datadog_metric_is_a_symptom_and_is_not_asked_again(monkeypatch):
    calls = {"metric": 0}

    def logs(_settings, _service, query, _limit, started_at=None):
        if query == "503":
            return "datadog service:checkout-api: ERROR gateway returned 503"
        return "datadog service:checkout-api: ERROR timeout status=503"

    def metric(_settings, _service, started_at=None):
        calls["metric"] += 1
        return (
            "datadog metric service:checkout-api trace.servlet.request.errors: "
            "last=12 peak=40 during the last 60 minutes."
        )

    monkeypatch.setattr(
        "incident_investigation_agent.services.gather.datadog.search_datadog_logs",
        logs,
    )
    monkeypatch.setattr(
        "incident_investigation_agent.services.gather.datadog.query_datadog_metric",
        metric,
    )
    settings = _settings(Path("examples/logs"), ("datadog",))
    batch = gather(settings, "checkout-api")
    assert calls["metric"] == 1
    symptoms = [item for item in batch.findings if item.kind == "symptom"]
    assert len(symptoms) == 1
    assert "last=12" in symptoms[0].summary
    assert "peak=40" in symptoms[0].summary
    assert batch.text.count("query_datadog_metric:") == 1
    assert "search_datadog 503:" in batch.text
    assert "search_datadog peak:" not in batch.text
    assert batch.spans == (
        Finding("timeline", "Datadog searched the last 60 minutes.", "search_datadog"),
    )


def test_an_unset_datadog_metric_is_unchecked_and_the_logs_stay(monkeypatch):
    def logs(_settings, _service, query, _limit, started_at=None):
        return "datadog service:checkout-api: ERROR vault timeout"

    monkeypatch.setattr(
        "incident_investigation_agent.services.gather.datadog.search_datadog_logs",
        logs,
    )
    settings = _settings(
        Path("examples/logs"),
        ("datadog",),
        datadog_api_key="secret-key",
        datadog_app_key="secret-app",
    )
    batch = gather(settings, "checkout-api")
    assert any(item.kind == "log" and "vault timeout" in item.summary for item in batch.findings)
    assert all(item.kind != "symptom" for item in batch.findings)
    assert batch.spans == (
        Finding("timeline", "Datadog searched the last 60 minutes.", "search_datadog"),
    )
    assert "Datadog metrics were not queried. Set DATADOG_METRIC." in batch.unchecked
    assert "secret-key" not in batch.text


def test_a_datadog_metric_with_no_points_is_a_miss():
    batch = _combine(
        [
            (
                "query_datadog_metric",
                "",
                "No Datadog points for service:checkout-api during the last 60 minutes.",
            )
        ]
    )
    assert batch.findings == ()
    assert batch.misses == ("query_datadog_metric",)


def test_a_failed_datadog_metric_is_not_checked():
    batch = _combine(
        [
            ("query_datadog_metric", "", "Datadog metric query failed: HTTP 401."),
            (
                "search_datadog",
                "timeout",
                "datadog service:checkout-api: ERROR vault timeout",
            ),
        ]
    )
    assert batch.unchecked == ("Datadog metric query failed: HTTP 401.",)
    assert [item.summary for item in batch.findings] == [
        "datadog service:checkout-api: ERROR vault timeout"
    ]
    assert batch.findings[0].kind == "log"


def test_note_prompt_leads_with_each_match_once():
    prompt = "Incident: Checkout\nSearches run before this note is written."
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
    assert "Searches run before this note is written." not in note
    assert note.count("vault timeout") == 1
    assert "api.log:4: vault connection timed out" in note
    assert note.index("vault timeout") < note.index("CloudWatch is not configured")
    assert note.index("CloudWatch is not configured") < note.index("No match for search_logs climbed.")
    assert note.endswith("Write the incident note from these lines.")


def test_a_finished_search_names_the_span_ending_now(monkeypatch):
    def logs(_settings, _service, query, _limit, started_at=None):
        return "checkout-api: ERROR timeout status=503"

    monkeypatch.setattr(
        "incident_investigation_agent.services.gather.cloudwatch.search_cloudwatch_logs",
        logs,
    )
    settings = _settings(Path("examples/logs"), ("cloudwatch",))
    batch = gather(settings, "checkout-api", started_at=datetime.now(timezone.utc))
    assert batch.spans == (
        Finding("timeline", "CloudWatch searched the last 60 minutes.", "search_cloudwatch"),
    )
    assert "search_cloudwatch minutes:" not in batch.text
    assert "search_cloudwatch cloudwatch:" not in batch.text
    assert "search_cloudwatch 503:" in batch.text
    assert any(item.kind == "log" and "status=503" in item.summary for item in batch.findings)


def test_an_older_case_names_the_span_from_its_start(monkeypatch):
    def logs(_settings, _service, query, _limit, started_at=None):
        return "No CloudWatch events matched 'timeout' in /aws/ecs/checkout-api during the last 60 minutes."

    def commits(_settings, _service, started_at=None):
        return "No commits on acme/checkout-api in the last 24 hours."

    monkeypatch.setattr(
        "incident_investigation_agent.services.gather.cloudwatch.search_cloudwatch_logs",
        logs,
    )
    monkeypatch.setattr(
        "incident_investigation_agent.services.gather.github.list_commits",
        commits,
    )
    settings = _settings(Path("examples/logs"), ("cloudwatch", "github"))
    opened = datetime(2026, 9, 22, 14, 2, tzinfo=timezone.utc)
    batch = gather(settings, "checkout-api", started_at=opened)
    assert [item.summary for item in batch.spans] == [
        "CloudWatch searched 60 minutes from 2026-09-22T14:02:00Z.",
        "GitHub searched 24 hours from 2026-09-22T14:02:00Z.",
    ]
    assert [item.kind for item in batch.spans] == ["timeline", "timeline"]
    assert [item.source for item in batch.spans] == ["search_cloudwatch", "list_recent_commits"]
    assert batch.findings == ()


def test_a_source_that_was_not_checked_does_not_name_a_span(monkeypatch):
    def logs(_settings, _service, query, _limit, started_at=None):
        return (
            "CloudWatch is not configured. Set CLOUDWATCH_LOG_GROUP_PREFIX "
            "or CLOUDWATCH_LOG_GROUPS."
        )

    monkeypatch.setattr(
        "incident_investigation_agent.services.gather.cloudwatch.search_cloudwatch_logs",
        logs,
    )
    settings = _settings(Path("examples/logs"), ("cloudwatch",))
    batch = gather(settings, "checkout-api")
    assert batch.spans == ()
    assert batch.findings == ()
    assert batch.unchecked


def test_the_note_is_told_which_span_was_searched():
    prompt = "Incident: Checkout\nSearches run before this note is written."
    batch = SearchBatch(
        "",
        (Finding("log", "api.log:3: vault timeout", "api.log"),),
        spans=(Finding("timeline", "CloudWatch searched the last 60 minutes.", "search_cloudwatch"),),
    )
    note = _note_prompt(prompt, batch)
    assert note.index("What was searched:") < note.index("CloudWatch searched the last 60 minutes.")
    assert note.index("CloudWatch searched the last 60 minutes.") < note.index("Matching lines:")
    assert note.index("Matching lines:") < note.index("vault timeout")


def test_investigate_text_stores_the_span_before_the_note(monkeypatch, tmp_path):
    from incident_investigation_agent.infrastructure.file_case import CaseStore
    from incident_investigation_agent.services.investigation import investigate_text

    def fake_gather(_settings, _service, _hint, _started):
        return SearchBatch(
            "",
            (Finding("log", "api.log:1: ERROR vault timeout", "api.log"),),
            spans=(Finding("timeline", "CloudWatch searched the last 60 minutes.", "search_cloudwatch"),),
        )

    def fake_agent(_settings):
        def run(note):
            assert "What was searched:" in note
            assert "CloudWatch searched the last 60 minutes." in note
            return "Impact: checkout is failing."

        return run

    monkeypatch.setattr("incident_investigation_agent.services.investigation.gather", fake_gather)
    monkeypatch.setattr(
        "incident_investigation_agent.services.investigation.build_note_agent",
        fake_agent,
    )
    monkeypatch.setattr(
        "incident_investigation_agent.services.investigation.message_text",
        lambda value: value,
    )
    store = CaseStore(tmp_path)
    report = investigate_text(
        _settings(tmp_path, ("cloudwatch",)),
        store,
        "Started: 2026-09-22T14:02:00+00:00\n",
        "checkout-api",
    )
    assert report == "Impact: checkout is failing."
    assert [item.summary for item in store.list()] == [
        "CloudWatch searched the last 60 minutes.",
        "api.log:1: ERROR vault timeout",
    ]


def _settings(log_dir: Path, connectors: tuple[str, ...], connector_timeout_seconds: int = 15, **overrides) -> Settings:
    values = dict(
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
        connector_timeout_seconds=connector_timeout_seconds,
    )
    values.update(overrides)
    return Settings(**values)
