"""Pull every enabled search at once, then hand the worker one combined set."""

from __future__ import annotations

import contextvars
import logging
import re
import threading
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

log = logging.getLogger("incident_investigation_agent.gather")

QUERIES = ("timeout", "timed out", "500")
_EXTRA_QUERIES = 3
_EXTRA_VERSIONS = 2
_EXTRA_CODES = 2
_WORD = re.compile(r"[A-Za-z][A-Za-z0-9_-]{2,}")
_VERSION = re.compile(r"\d+\.\d+\.\d+")
_STATUS_CODE = re.compile(r"(?<!\d)[1-5]\d{2}(?!\d)")
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
    "the call did not finish",
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
        batch = SearchBatch("No connectors are enabled.", ())
        _log_search(names, batch)
        return batch
    blocks = _collect(jobs, settings.connector_timeout_seconds)
    batch = _combine(blocks)
    _log_search(names, batch)
    return batch


def _log_search(names: tuple[str, ...], batch: SearchBatch) -> None:
    log.info(
        "search finished connectors=%s findings=%s misses=%s unchecked=%s",
        ",".join(names) or "-",
        len(batch.findings),
        len(batch.misses),
        len(batch.unchecked),
    )


def _queries(hint: str, service: str | None) -> tuple[str, ...]:
    """Search timeout, timed out, and 500, then a version or status code named in the case.

    The version and the status code are kept even when they are written after the
    ordinary words. A line that only says ``status=503`` would otherwise be missed.
    ``500`` is already a default search, so a case that says ``500s`` does not
    search it twice. A word ending in "ed" or "ing" is shortened, so "deployed"
    matches a line that says "deploy".
    """
    blocked = set(_STOP)
    blocked.update(QUERIES)
    blocked.update(word for query in QUERIES for word in query.split())
    if service:
        blocked.add(service.lower())
        blocked.update(part.lower() for part in re.split(r"[^A-Za-z0-9]+", service) if part)
    versions: list[str] = []
    for token in _VERSION.findall(hint):
        if token in versions:
            continue
        versions.append(token)
        if len(versions) == _EXTRA_VERSIONS:
            break
    codes: list[str] = []
    for token in _STATUS_CODE.findall(hint):
        if token in codes or token in QUERIES:
            continue
        codes.append(token)
        if len(codes) == _EXTRA_CODES:
            break
    extras: list[str] = []
    for token in _WORD.findall(hint):
        word = token.lower()
        folded = _fold(word)
        chosen = word if folded in blocked else folded
        if chosen in blocked or chosen in extras:
            continue
        extras.append(chosen)
        if len(extras) == _EXTRA_QUERIES:
            break
    return (*QUERIES, *versions, *codes, *extras)


def _fold(word: str) -> str:
    """Use the shorter form, so a case that says "deployed" still matches "deploy"."""
    for suffix in ("ing", "ed"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 4:
            return word[: -len(suffix)]
    return word


@dataclass(frozen=True)
class _Job:
    label: str
    query: str
    call: object


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
            jobs.append(_Job("list_recent_commits", "", lambda: github.list_commits(settings, service)))
            continue
        label, function = searchers[name]
        for query in queries:
            jobs.append(
                _Job(
                    label,
                    query,
                    lambda query=query, function=function: function(settings, service, query, 20),
                )
            )
    return jobs


def _collect(jobs: list[_Job], timeout: float) -> list[tuple[str, str, str]]:
    """Run every search, and stop waiting when one call passes the timeout.

    The pool worker joins a daemon thread. A stuck socket cannot hold that
    worker, or the investigation, until the run timeout. The other sources
    are kept.
    """
    workers = min(8, len(jobs))
    pool = ThreadPoolExecutor(max_workers=workers)
    try:
        futures = [_submit(pool, job.call, timeout) for job in jobs]
        bodies = [future.result() for future in futures]
    finally:
        pool.shutdown(wait=True, cancel_futures=True)
    blocks: list[tuple[str, str, str]] = []
    for job, body in zip(jobs, bodies):
        if body is None:
            log.warning(
                "search timed out source=%s query=%s seconds=%s",
                job.label,
                job.query or "-",
                timeout,
            )
            blocks.append((job.label, job.query, _timeout_text(job.label, timeout)))
            continue
        blocks.append((job.label, job.query, body))
    return blocks


def _submit(pool: ThreadPoolExecutor, call, timeout: float):
    """Copy the case and run on this thread, then hand the copy to the pool."""
    context = contextvars.copy_context()
    return pool.submit(_wait, context, call, timeout)


def _wait(context: contextvars.Context, call, timeout: float):
    holder: dict[str, object] = {}

    def run() -> None:
        try:
            holder["value"] = context.run(call)
        except Exception as exc:
            holder["error"] = exc

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join(timeout)
    if "error" in holder:
        raise holder["error"]
    if "value" in holder:
        return holder["value"]
    return None


def _timeout_text(label: str, timeout: float) -> str:
    prefix = {
        "search_logs": "Log search failed",
        "search_cloudwatch": "CloudWatch search failed",
        "search_datadog": "Datadog search failed",
        "search_loki": "Loki search failed",
        "list_recent_commits": "Commit list failed",
    }.get(label, "Search failed")
    seconds = int(timeout) if float(timeout).is_integer() else timeout
    unit = "second" if seconds == 1 else "seconds"
    return f"{prefix}: the call did not finish within {seconds} {unit}."


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
