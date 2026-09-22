from incident_investigation_agent.logs import search_logs


def test_search_finds_matching_line(tmp_path):
    log = tmp_path / "api.log"
    log.write_text("INFO ok\nERROR vault timeout\n", encoding="utf-8")
    result = search_logs(tmp_path, "Vault")
    assert "api.log:2:" in result
    assert "vault timeout" in result


def test_search_reports_a_miss(tmp_path):
    (tmp_path / "api.log").write_text("INFO ok\n", encoding="utf-8")
    result = search_logs(tmp_path, "timeout")
    assert result.startswith("No lines matched")
