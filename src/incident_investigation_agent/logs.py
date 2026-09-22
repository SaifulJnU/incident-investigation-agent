"""Read local log files without depending on the agent SDK."""

from __future__ import annotations

from pathlib import Path


def search_logs(log_dir: Path, query: str, limit: int = 20) -> str:
    needle = query.strip()
    if not needle:
        return "Query is empty."
    if limit < 1:
        return "Limit must be at least 1."
    if not log_dir.exists():
        return f"Log directory does not exist: {log_dir}"

    matches: list[str] = []
    files = sorted(path for path in log_dir.rglob("*") if path.is_file())
    for path in files:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            matches.append(f"{path.name}: unreadable ({exc})")
            continue
        for line_no, line in enumerate(text.splitlines(), start=1):
            if needle.lower() in line.lower():
                matches.append(f"{path.name}:{line_no}: {line.strip()}")
                if len(matches) >= limit:
                    return "\n".join(matches)
    if not matches:
        return f"No lines matched {needle!r} under {log_dir}."
    return "\n".join(matches)
