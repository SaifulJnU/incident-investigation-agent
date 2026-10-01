from incident_investigation_agent.infrastructure.file_case import CaseStore
from incident_investigation_agent.services.gather import Finding
from incident_investigation_agent.services.investigation import _record_findings


def test_case_round_trip(tmp_path):
    store = CaseStore(tmp_path)
    assert store.list() == []
    store.add("symptom", "Checkout returns 500", "pager")
    store.add("timeline", "Deploy of payments-api at 14:02", "operator")
    items = store.list()
    assert [item.kind for item in items] == ["symptom", "timeline"]
    assert items[0].summary == "Checkout returns 500"
    assert items[1].source == "operator"


def test_a_second_run_does_not_copy_a_log_line(tmp_path):
    store = CaseStore(tmp_path)
    store.add("log", "api.log:1: ERROR vault timeout", "api.log")
    _record_findings(
        store,
        (
            Finding("log", "api.log:1: ERROR vault timeout", "api.log"),
            Finding("log", "api.log:2: ERROR status=500", "api.log"),
        ),
    )
    assert [item.summary for item in store.list()] == [
        "api.log:1: ERROR vault timeout",
        "api.log:2: ERROR status=500",
    ]
