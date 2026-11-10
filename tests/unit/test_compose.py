import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "docker-compose.yml"
PORT = re.compile(r"^\s*-\s+[\"']?(?:(\d+\.\d+\.\d+\.\d+):)?(\d+):(\d+)[\"']?\s*$")


def test_compose_file_publishes_only_on_localhost():
    text = COMPOSE.read_text(encoding="utf-8")
    assert text.lower().startswith("# laptop only")
    assert "Local production shape" not in text
    assert "/var/run/docker.sock:/var/run/docker.sock" in text
    assert "not a deploy" in text

    published = []
    for line in text.splitlines():
        match = PORT.match(line)
        if match is None:
            continue
        host, host_port, _container = match.groups()
        published.append(host_port)
        assert host == "127.0.0.1"

    assert set(published) >= {"5432", "4566", "8000", "8080", "8090"}
