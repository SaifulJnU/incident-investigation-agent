"""Pull every enabled search at once, then hand the worker one combined set."""

from __future__ import annotations

import re
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

QUERIES = ("timeout", "timed out", "500")
_EXTRA_QUERIES = 3
_WORD = re.compile(r"[A-Za-z][A-Za-z0-9_-]{2,}")
_STOP = frozenset(
    {
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
        "error",
        "errors",
        "incident",
        "service",
        "started",
        "what",
        "know",
        "evidence",
        "already",
        "recorded",
        "source",
        "severity",
        "sev1",
        "sev2",
        "sev3",
        "sev4",
        "case",
        "during",
        "while",
        "when",
        "have",
        "been",
        "were",
        "was",
        "not",
        "but",
        "its",
        "our",
        "their",
        "they",
        "api",
        "info",
        "warn",
        "warning",
        "request",
        "status",
        "unknown",
        "about",
        "over",
        "under",
        "than",
        "then",
        "also",
        "just",
        "only",
        "still",
        "looks",
        "healthy",
    }
)

# Connector status sentences, not words that can appear inside a real log line.
# "search failed" and "returned no" are real log phrases, so only the connector's
# own sentence is matched.
_STATUS = (
    "no lines matched",
    "log directory does not exist",
    "query is empty",
    "limit must be at least",
    "is not configured",
    "was not searched",
    "were not searched",
    "was not queried",
    "no service is set",
    "cloudwatch search failed",
    "datadog search failed",
    "loki search failed",
    "commit list failed",
    "invalid service",
    "github returned no ",
    "datadog returned no ",
    "has no repository",
    "no cloudwatch events matched",
    "no datadog logs matched",
    "no loki lines matched",
    "no commits on ",
    "must be a label",
    "must be an https",
)
_MISS = (
    "no lines matched",
    "no cloudwatch events matched",
    "no datadog logs matched",
    "no loki lines matched",
    "no commits on ",
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
    misses: tuple[str, ...] = ()
    unchecked: tuple[str, ...] = ()


def gather(settings: Settings, service: str | None, hint: str = "") -> SearchBatch:
    names = enabled_connectors(settings.app_env, settings.connectors)
    jobs = _jobs(settings, service, names, _queries(hint, service))
    if not jobs:
        return SearchBatch("No connectors are enabled.", ())
    with ThreadPoolExecutor(max_workers=min(8, len(jobs))) as pool:
        blocks = list(pool.map(lambda job: job(), jobs))
    return _combine(blocks)


def _queries(hint: str, service: str | None) -> tuple[str, ...]:
    """Always search timeout, timed out, and 500, then a few words from the case itself."""
    blocked = set(_STOP)
    blocked.update(QUERIES)
    blocked.update(word for query in QUERIES for word in query.split())
    if service:
        blocked.add(service.lower())
        blocked.update(part.lower() for part in re.split(r"[^A-Za-z0-9]+", service) if part)
    extras: list[str] = []
    for token in _WORD.findall(hint):
        word = token.lower()
        if word in blocked or word in extras:
            continue
        extras.append(word)
        if len(extras) == _EXTRA_QUERIES:
            break
    return (*QUERIES, *extras)


def _jobs(settings: Settings, service: str | None, names: tuple[str, ...], queries: tuple[str, ...]):
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
        for query in queries:
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
    misses: list[str] = []
    unchecked: list[str] = []
    unchecked_seen: set[str] = set()
    for label, query, body in blocks:
        title = f"{label} {query}".strip()
        lines.append(f"{title}:")
        lines.append(body.strip() or "(empty)")
        kind = "change" if label == "list_recent_commits" else "log"
        hits = 0
        status = ""
        for raw in body.splitlines():
            summary = raw.strip()
            if not summary:
                continue
            if _status_line(summary):
                status = status or summary
                continue
            hits += 1
            if summary in seen:
                continue
            seen.add(summary)
            findings.append(Finding(kind, summary, _source(label, summary)))
        if hits:
            continue
        if status and not _miss_line(status):
            if status not in unchecked_seen:
                unchecked_seen.add(status)
                unchecked.append(status)
            continue
        misses.append(title)
    return SearchBatch("\n".join(lines), tuple(findings), tuple(misses), tuple(unchecked))


def _status_line(line: str) -> bool:
    head = line.strip().lower()
    if not head:
        return True
    return any(part in head for part in _STATUS)


def _miss_line(line: str) -> bool:
    head = line.strip().lower()
    return any(part in head for part in _MISS)


def _source(label: str, summary: str) -> str:
    if label == "search_logs" and ":" in summary:
        return summary.split(":", 1)[0]
    return label
