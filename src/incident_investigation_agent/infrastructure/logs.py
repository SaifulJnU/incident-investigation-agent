"""Read local log files without depending on the agent SDK."""

from __future__ import annotations

import re
from pathlib import Path

_SKIP = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "that",
    "this",
    "after",
    "before",
    "into",
    "http",
    "https",
    "post",
    "get",
}

_SERVICE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,118}$")


def scoped_log_dir(log_dir: Path, service: str) -> Path:
    """Logs for one service. The search must not walk up into other services."""
    if not _SERVICE_NAME.fullmatch(service):
        raise ValueError(f"Invalid service name {service!r}.")
    root = log_dir.resolve()
    scoped = (root / service).resolve()
    if root not in scoped.parents:
        raise ValueError(f"Invalid service name {service!r}.")
    return scoped


def search_logs(log_dir: Path, query: str, limit: int = 20) -> str:
    needle = query.strip()
    if not needle:
        return "Query is empty."
    if limit < 1:
        return "Limit must be at least 1."
    if not log_dir.exists():
        return f"Log directory does not exist: {log_dir}"

    files = sorted(path for path in log_dir.rglob("*") if path.is_file())
    exact = _scan(files, needle.lower(), limit)
    if exact:
        return "\n".join(exact)

    tokens = [
        token
        for token in re.findall(r"[A-Za-z0-9]{3,}", needle)
        if token.lower() not in _SKIP
    ]
    seen: set[str] = set()
    token_hits: list[str] = []
    for token in tokens:
        for line in _scan(files, token.lower(), limit):
            if line not in seen:
                seen.add(line)
                token_hits.append(line)
            if len(token_hits) >= limit:
                return "\n".join(token_hits)
    if token_hits:
        return "\n".join(token_hits)
    names = ", ".join(path.name for path in files[:8]) or "no files"
    return (
        f"No lines matched {needle!r}. Files searched: {names}. "
        "Search again with one short word, such as a status code or an error word."
    )


def _scan(files: list[Path], needle: str, limit: int) -> list[str]:
    matches: list[str] = []
    for path in files:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            matches.append(f"{path.name}: unreadable ({exc})")
            continue
        for line_no, line in enumerate(text.splitlines(), start=1):
            if needle in line.lower():
                matches.append(f"{path.name}:{line_no}: {line.strip()}")
                if len(matches) >= limit:
                    return matches
    return matches
