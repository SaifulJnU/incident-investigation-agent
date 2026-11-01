from incident_investigation_agent.cli import main


def test_the_command_line_uses_the_same_note_path(monkeypatch, capsys):
    seen = {}

    def fake(_settings, store, prompt, service):
        seen["prompt"] = prompt
        seen["service"] = service
        seen["store"] = store
        return "Impact: checkout is failing."

    monkeypatch.setattr("incident_investigation_agent.cli.investigate_text", fake)
    main(["checkout 500s"])
    captured = capsys.readouterr()
    assert seen["prompt"] == "checkout 500s"
    assert seen["service"] is None
    assert seen["store"] is not None
    assert captured.out.strip() == "Impact: checkout is failing."
    assert "Provider:" in captured.err
