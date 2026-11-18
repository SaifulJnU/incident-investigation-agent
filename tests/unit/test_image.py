from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_console_proxies_the_metrics_scrape():
    text = (ROOT / "deploy" / "nginx.conf").read_text(encoding="utf-8")
    assert "location = /metrics" in text
    assert "proxy_pass http://$api_upstream;" in text


def test_api_image_serves_while_migrations_retry():
    dockerfile = (ROOT / "deploy" / "api.Dockerfile").read_text(encoding="utf-8")
    command = dockerfile.splitlines()[-1]
    assert "alembic upgrade head" in command
    assert "uvicorn" in command
    assert "&" in command
    assert "before it serves" not in dockerfile

    notes = [
        ROOT / "prd" / "schema-design.md",
        ROOT / "prd" / "user-manual.md",
        ROOT / "README.md",
    ]
    for path in notes:
        text = path.read_text(encoding="utf-8")
        assert "before it serves" not in text
        assert "/api/ready" in text
        assert "503" in text
