"""Pull every enabled search at once, then hand the worker one combined set."""

from __future__ import annotations

import contextvars
import logging
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta

from incident_investigation_agent.core.config import Settings, enabled_connectors
from incident_investigation_agent.infrastructure.connectors import (
    cloudwatch,
    datadog,
    github,
    local_logs,
    loki,
    mcp,
)
from incident_investigation_agent.infrastructure.connectors.window import during, search_span

log = logging.getLogger("incident_investigation_agent.gather")

QUERIES = ("timeout", "timed out", "500")
# A matching line stored on the case. A longer line keeps its start.
FINDING_TEXT_LIMIT = 2000
_CLIP = "..."
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
    "datadog metric query failed",
    "datadog metrics were not queried",
    "no datadog points",
    "loki search failed",
    "mcp search failed",
    "mcp returned no ",
    "was not called",
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
    "no datadog points",
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
    spans: tuple[Finding, ...] = ()


# A finished search stores one timeline line. The unit matches the connector lookback.
# Logs and the Datadog metric share one line. Local logs and MCP have no time index.
_SPAN_SOURCES = (
    ("cloudwatch", ("search_cloudwatch",), "CloudWatch", "cloudwatch_lookback_minutes", "minutes"),
    ("datadog", ("search_datadog", "query_datadog_metric"), "Datadog", "datadog_lookback_minutes", "minutes"),
    ("loki", ("search_loki",), "Loki", "loki_lookback_minutes", "minutes"),
    ("github", ("list_recent_commits",), "GitHub", "github_lookback_hours", "hours"),
)


def gather(
    settings: Settings,
    service: str | None,
    hint: str = "",
    started_at: datetime | None = None,
) -> SearchBatch:
    names = enabled_connectors(settings.app_env, settings.connectors)
    queries = _queries(hint, service)
    jobs = _jobs(settings, service, names, queries, started_at=started_at)
    if not jobs:
        batch = SearchBatch("No connectors are enabled.", ())
        _log_search(names, batch)
        return batch
    timeout = settings.connector_timeout_seconds
    batch = _combine(_collect(jobs, timeout))
    follow = _follow_query(batch.findings, queries, service)
    if follow:
        more = _jobs(
            settings,
            service,
            names,
            (follow,),
            include_github=False,
            include_metric=False,
            started_at=started_at,
        )
        if more:
            batch = _merge(batch, _combine(_collect(more, timeout)))
    batch = _with_spans(batch, _span_findings(settings, names, batch, started_at))
    _log_search(names, batch)
    return batch


def _log_search(names: tuple[str, ...], batch: SearchBatch) -> None:
    log.info(
        "search finished connectors=%s findings=%s misses=%s unchecked=%s spans=%s",
        ",".join(names) or "-",
        len(batch.findings),
        len(batch.misses),
        len(batch.unchecked),
        len(batch.spans),
    )


def _with_spans(batch: SearchBatch, spans: tuple[Finding, ...]) -> SearchBatch:
    if not spans:
        return batch
    return SearchBatch(batch.text, batch.findings, batch.misses, batch.unchecked, spans)


def _span_findings(
    settings: Settings,
    names: tuple[str, ...],
    batch: SearchBatch,
    started_at: datetime | None,
) -> tuple[Finding, ...]:
    """One timeline line for each time-bounded search that finished.

    The sentence uses the same span the connector queried. A source that was
    not checked does not get a line. The follow-up search has already been
    chosen, so this sentence is not searched again.
    """
    enabled = set(names)
    findings: list[Finding] = []
    for name, labels, title, attr, unit in _SPAN_SOURCES:
        if name not in enabled:
            continue
        source = _finished_source(batch, labels)
        if source is None:
            continue
        length = getattr(settings, attr)
        lookback = timedelta(hours=length) if unit == "hours" else timedelta(minutes=length)
        start, _end, anchored = search_span(started_at, lookback)
        span = during(f"{length} {unit}", anchored, start)
        findings.append(Finding("timeline", f"{title} searched {span}.", source))
    return tuple(findings)


def _finished_source(batch: SearchBatch, labels: tuple[str, ...]) -> str | None:
    """The connector label that returned a line or a miss, preferring the first."""
    label_set = set(labels)
    found = None
    for item in batch.findings:
        if item.kind == "timeline" or item.source not in label_set:
            continue
        if item.source == labels[0]:
            return item.source
        found = found or item.source
    for miss in batch.misses:
        head = miss.split(" ", 1)[0]
        if head not in label_set:
            continue
        if head == labels[0]:
            return head
        found = found or head
    return found


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


_FILE_PREFIX = re.compile(r"^[^\s:]+:\d+:\s+")
_DATADOG_LABEL = re.compile(r"^datadog \S+: ")
_LOKI_LABEL = re.compile(r"^loki \S+: ")
_GROUP_LABEL = re.compile(r"^[^\s:]+: ")
_COMMIT_LABEL = re.compile(
    r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\s+[0-9a-fA-F]{1,40}\s+"
    r"(?:\d{4}-\d{2}-\d{2}T[\d:]+Z\s+)?"
)


def _follow_query(findings: tuple[Finding, ...], queries: tuple[str, ...], service: str | None) -> str | None:
    """One status code, version, or word from the lines already found.

    The first search does not know this token. A code or a version is used
    before an ordinary word, because that is the sharper second question.
    The token comes from the log message or the commit subject. The connector
    name, the log group, and the repository are labels this product added.
    A metric line is skipped. Its words were written here, not found in a log.
    """
    blocked = _blocked(queries, service)
    texts = [_follow_text(item) for item in findings if item.kind != "symptom"]
    for text in texts:
        for token in _STATUS_CODE.findall(text):
            if token not in blocked:
                return token
    for text in texts:
        for token in _VERSION.findall(text):
            if token not in blocked:
                return token
    for text in texts:
        for token in _WORD.findall(text):
            word = _fold(token.lower())
            if word in blocked or len(word) < 4:
                continue
            return word
    return None


def _follow_text(item: Finding) -> str:
    """The part of a stored line that came back from the other system."""
    text = _FILE_PREFIX.sub("", item.summary, count=1)
    if item.source == "search_datadog":
        return _DATADOG_LABEL.sub("", text, count=1)
    if item.source == "search_loki":
        return _LOKI_LABEL.sub("", text, count=1)
    if item.source == "search_cloudwatch":
        return _GROUP_LABEL.sub("", text, count=1)
    if item.source == "list_recent_commits":
        return _COMMIT_LABEL.sub("", text, count=1)
    return text


def _blocked(queries: tuple[str, ...], service: str | None) -> set[str]:
    blocked = set(_STOP)
    blocked.update(query.lower() for query in queries)
    for query in queries:
        blocked.update(part.lower() for part in re.split(r"[^A-Za-z0-9]+", query) if part)
    if service:
        blocked.add(service.lower())
        blocked.update(part.lower() for part in re.split(r"[^A-Za-z0-9]+", service) if part)
    return blocked


def _merge(first: SearchBatch, second: SearchBatch) -> SearchBatch:
    seen = {item.summary for item in first.findings}
    findings = list(first.findings)
    for item in second.findings:
        if item.summary in seen:
            continue
        seen.add(item.summary)
        findings.append(item)
    misses = list(first.misses)
    for miss in second.misses:
        if miss not in misses:
            misses.append(miss)
    unchecked = list(first.unchecked)
    seen_unchecked = set(unchecked)
    for line in second.unchecked:
        if line not in seen_unchecked:
            seen_unchecked.add(line)
            unchecked.append(line)
    text = first.text if not second.text else f"{first.text}\n{second.text}"
    spans = list(first.spans)
    seen_spans = {item.summary for item in spans}
    for item in second.spans:
        if item.summary in seen_spans:
            continue
        seen_spans.add(item.summary)
        spans.append(item)
    return SearchBatch(text, tuple(findings), tuple(misses), tuple(unchecked), tuple(spans))


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


def _jobs(
    settings: Settings,
    service: str | None,
    names: tuple[str, ...],
    queries: tuple[str, ...],
    include_github: bool = True,
    include_metric: bool = True,
    started_at: datetime | None = None,
):
    jobs = []
    searchers = {
        "local_logs": ("search_logs", local_logs.search_local_logs),
        "cloudwatch": ("search_cloudwatch", cloudwatch.search_cloudwatch_logs),
        "datadog": ("search_datadog", datadog.search_datadog_logs),
        "loki": ("search_loki", loki.search_loki_logs),
        "mcp": ("search_mcp", mcp.search_mcp),
    }
    timed = {"cloudwatch", "datadog", "loki"}
    for name in names:
        if name == "github":
            if include_github:
                jobs.append(
                    _Job(
                        "list_recent_commits",
                        "",
                        lambda started_at=started_at: github.list_commits(
                            settings, service, started_at=started_at
                        ),
                    )
                )
            continue
        if name == "datadog" and include_metric:
            jobs.append(
                _Job(
                    "query_datadog_metric",
                    "",
                    lambda started_at=started_at: datadog.query_datadog_metric(
                        settings, service, started_at=started_at
                    ),
                )
            )
        label, function = searchers[name]
        for query in queries:
            if name in timed:
                call = lambda query=query, function=function, started_at=started_at: function(
                    settings, service, query, 20, started_at
                )
            else:
                call = lambda query=query, function=function: function(settings, service, query, 20)
            jobs.append(_Job(label, query, call))
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
        "query_datadog_metric": "Datadog metric query failed",
        "search_loki": "Loki search failed",
        "search_mcp": "MCP search failed",
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
        kind = {"list_recent_commits": "change", "query_datadog_metric": "symptom"}.get(label, "log")
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
            summary = _clip_finding(summary)
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


def _clip_finding(summary: str) -> str:
    """Keep the start of a long line so one hit cannot fill the case."""
    if len(summary) <= FINDING_TEXT_LIMIT:
        return summary
    keep = FINDING_TEXT_LIMIT - len(_CLIP)
    return summary[:keep].rstrip() + _CLIP


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
