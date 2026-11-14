from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _pins(path: Path) -> dict[str, str]:
    pins = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        assert ">=" not in line
        assert "AppData" not in line
        name, version = line.split("==", 1)
        version = version.split(";", 1)[0].strip()
        assert name not in pins
        pins[name] = version
    return pins


def test_python_dependencies_are_pinned():
    runtime = _pins(ROOT / "requirements.txt")
    dev = _pins(ROOT / "requirements-dev.txt")
    assert runtime["fastapi"] == dev["fastapi"]
    assert "pytest" not in runtime
    assert dev["pytest"]
    drifted = {name: version for name, version in runtime.items() if dev.get(name) != version}
    assert drifted == {}

    workflow = (ROOT / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")
    assert "pip install -r requirements-dev.txt" in workflow
    assert "pip install --no-deps -e ." in workflow
    assert 'pip install -e ".[dev]"' not in workflow

    dockerfile = (ROOT / "deploy" / "api.Dockerfile").read_text(encoding="utf-8")
    assert "pip install --no-cache-dir -r requirements.txt" in dockerfile
    assert "pip install --no-cache-dir --no-deps ." in dockerfile

    manual = (ROOT / "prd" / "user-manual.md").read_text(encoding="utf-8")
    assert "pip install -r requirements-dev.txt" in manual
    assert 'pip install -e ".[dev]"' not in manual
