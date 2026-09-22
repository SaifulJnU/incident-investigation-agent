from incident_investigation_agent.case import CaseStore


def test_case_round_trip(tmp_path):
    store = CaseStore(tmp_path)
    assert store.list() == []
    store.add("symptom", "Checkout returns 500", "pager")
    store.add("timeline", "Deploy of payments-api at 14:02", "operator")
    items = store.list()
    assert [item.kind for item in items] == ["symptom", "timeline"]
    assert items[0].summary == "Checkout returns 500"
    assert items[1].source == "operator"
