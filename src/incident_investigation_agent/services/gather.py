"""Pull every enabled search at once, then hand the worker one combined set."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from incident_investigation_agent.core.config import Settings, enabled_connectors
from incident_investigation_agent.infrastructure.connectors import (
    cloudwatch,
    datadog,
    github,
    local_logs,
    loki,
)

QUERIES = ("timeout", "500")

_MISS = (
    "no lines matched",
    "not configured",
    "was not searched",
    "not searched",
    "does not exist",
    "query is empty",
    "no service is set",
    "no commits",
    "commit list failed",
    "invalid service",
    "not queried",
    "returned no",
    "has no repository",
    "must be",
    "limit must",
)


@dataclass(frozen=True)
class Finding:
    kind: str
    summary: str
    source: str


@dataclass(frozen=True)
class SearchBatch:
    text: str
    findings: tuple[Finding, ...]


def gather(settings: Settings, service: str | None) -> SearchBatch:
    names = enabled_connectors(settings.app_env, settings.connectors)
    jobs = _jobs(settings, service, names)
    if not jobs:
        return SearchBatch("No connectors are enabled.", ())
    with ThreadPoolExecutor(max_workers=min(8, len(jobs))) as pool:
        blocks = list(pool.map(lambda job: job(), jobs))
    return _combine(blocks)


def _jobs(settings: Settings, service: str | None, names: tuple[str, ...]):
    jobs = []
    searchers = {
        "local_logs": ("search_logs", local_logs.search_local_logs),
        "cloudwatch": ("search_cloudwatch", cloudwatch.search_cloudwatch_logs),
        "datadog": ("search_datadog", datadog.search_datadog_logs),
        "loki": ("search_loki", loki.search_loki_logs),
    }
    for name in names:
        if name == "github":
            jobs.append(lambda: ("list_recent_commits", "", github.list_commits(settings, service)))
            continue
        label, function = searchers[name]
        for query in QUERIES:
            jobs.append(
                lambda label=label, query=query, function=function: (
                    label,
                    query,
                    function(settings, service, query, 20),
                )
            )
    return jobs


def _combine(blocks: list[tuple[str, str, str]]) -> SearchBatch:
    lines: list[str] = []
    findings: list[Finding] = []
    seen: set[str] = set()
    for label, query, body in blocks:
        title = f"{label} {query}".strip()
        lines.append(f"{title}:")
        lines.append(body.strip() or "(empty)")
        if _miss(body):
            continue
        kind = "change" if label == "list_recent_commits" else "log"
        for raw in body.splitlines():
            summary = raw.strip()
            if not summary or summary in seen:
                continue
            seen.add(summary)
            findings.append(Finding(kind, summary, _source(label, summary)))
    return SearchBatch("\n".join(lines), tuple(findings))


def _miss(body: str) -> bool:
    head = body.strip().lower()
    if not head:
        return True
    return any(part in head for part in _MISS)


def _source(label: str, summary: str) -> str:
    if label == "search_logs" and ":" in summary:
        return summary.split(":", 1)[0]
    return label
