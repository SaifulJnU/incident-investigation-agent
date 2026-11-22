"""Read Datadog logs and one metric for the case service. Does not post either."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from urllib.parse import urlencode

from strands import tool

from incident_investigation_agent.core.config import Settings
from incident_investigation_agent.infrastructure.connectors.http import ConnectorError, request_json
from incident_investigation_agent.infrastructure.connectors.mapping import clean_query, require_service
from incident_investigation_agent.infrastructure.connectors.window import during, epoch_ms, search_span, stamp

_SITE = re.compile(r"^[a-z0-9][a-z0-9.-]{0,200}$")
_TAG = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_METRIC = re.compile(r"^[A-Za-z0-9_.:{}*,()+/ -]{1,300}$")
_METRIC_NAME = re.compile(r"^[A-Za-z0-9_.:]{1,120}$")
_SERIES_LIMIT = 3


def tools_for(settings: Settings, service: str | None):
    @tool
    def search_datadog(query: str, limit: int = 20) -> str:
        """Search Datadog logs for this case's service. Read-only.

        Args:
            query: A short word to find, combined with the service tag
            limit: Maximum log events to return
        """
        return search_datadog_logs(settings, service, query, limit)

    @tool
    def query_datadog_metric() -> str:
        """Read one Datadog metric for this case's service. Read-only."""
        return _read_datadog_metric(settings, service)

    return [search_datadog, query_datadog_metric]


def search_datadog_logs(
    settings: Settings,
    service: str | None,
    query: str,
    limit: int,
    started_at: datetime | None = None,
) -> str:
    scoped = require_service(service)
    if scoped is None:
        return "No service is set on this case, so Datadog was not searched."
    needle = clean_query(query)
    if needle is None:
        return "Query is empty or has characters Datadog search does not send."
    missing = _missing(settings)
    if missing:
        return f"Datadog is not configured. Set {missing}."
    tag = settings.datadog_service_tag
    if not _TAG.fullmatch(tag):
        return "DATADOG_SERVICE_TAG must be a label such as service."
    capped = _limit(limit)
    start, end, anchored = search_span(
        started_at, timedelta(minutes=settings.datadog_lookback_minutes)
    )
    span = during(f"{settings.datadog_lookback_minutes} minutes", anchored, start)
    if anchored:
        window_from, window_to = stamp(start), stamp(end)
    else:
        window_from, window_to = f"now-{settings.datadog_lookback_minutes}m", "now"
    url = f"https://api.{settings.datadog_site}/api/v2/logs/events/search"
    payload = {
        "filter": {
            "query": f"{tag}:{scoped} {needle}",
            "from": window_from,
            "to": window_to,
        },
        "page": {"limit": capped},
        "sort": "-timestamp",
    }
    headers = {
        "DD-API-KEY": settings.datadog_api_key,
        "DD-APPLICATION-KEY": settings.datadog_app_key,
    }
    try:
        body = request_json(
            url,
            method="POST",
            headers=headers,
            payload=payload,
            timeout=settings.connector_timeout_seconds,
        )
    except ConnectorError as exc:
        return f"Datadog search failed: {exc}"
    rows = body.get("data") if isinstance(body, dict) else None
    if not rows:
        return (
            f"No Datadog logs matched {needle!r} for {tag}:{scoped} "
            f"during {span}."
        )
    lines = []
    for row in rows[:capped]:
        attributes = row.get("attributes") if isinstance(row, dict) else None
        message = ""
        if isinstance(attributes, dict):
            message = str(attributes.get("message") or "").strip().replace("\n", " ")
        if message:
            lines.append(f"datadog {tag}:{scoped}: {message[:500]}")
    if not lines:
        return f"Datadog returned no message text for {tag}:{scoped}."
    return "\n".join(lines)


def query_datadog_metric(
    settings: Settings,
    service: str | None,
    *,
    started_at: datetime | None = None,
) -> str:
    """Read one configured metric for this service over the same span as the logs.

    ``DATADOG_METRIC`` is the query, and ``SERVICE`` in it is this case's
    service. A query that does not name that service is not called. The
    result is last and peak, which the note can quote. This does not post
    a metric.
    """
    scoped = require_service(service)
    if scoped is None:
        return "No service is set on this case, so Datadog metrics were not queried."
    missing = _missing(settings)
    if missing:
        return f"Datadog is not configured. Set {missing}."
    tag = settings.datadog_service_tag
    if not _TAG.fullmatch(tag):
        return "DATADOG_SERVICE_TAG must be a label such as service."
    template = " ".join(settings.datadog_metric.split())
    if not template:
        return "Datadog metrics were not queried. Set DATADOG_METRIC."
    query = _scoped_metric(template, tag, scoped)
    if query is None:
        return (
            "Datadog metric query does not name this service, so it was not called. "
            f"DATADOG_METRIC must contain {tag}:SERVICE."
        )
    if _names_other_service(query, tag, scoped):
        return "Datadog metric query reads another service, so it was not called."
    start, end, anchored = search_span(
        started_at, timedelta(minutes=settings.datadog_lookback_minutes)
    )
    span = during(f"{settings.datadog_lookback_minutes} minutes", anchored, start)
    params = urlencode(
        {
            "from": epoch_ms(start) // 1000,
            "to": epoch_ms(end) // 1000,
            "query": query,
        }
    )
    url = f"https://api.{settings.datadog_site}/api/v1/query?{params}"
    headers = {
        "DD-API-KEY": settings.datadog_api_key,
        "DD-APPLICATION-KEY": settings.datadog_app_key,
    }
    try:
        body = request_json(
            url,
            headers=headers,
            timeout=settings.connector_timeout_seconds,
        )
    except ConnectorError as exc:
        return f"Datadog metric query failed: {exc}"
    if not isinstance(body, dict):
        return "Datadog metric query failed: the service returned a response that was not a metric."
    if body.get("status") == "error" or body.get("error"):
        detail = str(body.get("error") or "error").replace("\n", " ")[:200]
        return f"Datadog metric query failed: {detail}"
    series = body.get("series")
    lines = _metric_lines(series if isinstance(series, list) else [], tag, scoped, span)
    if not lines:
        return f"No Datadog points for {tag}:{scoped} during {span}."
    return "\n".join(lines)


_read_datadog_metric = query_datadog_metric


def _scoped_metric(template: str, tag: str, scoped: str) -> str | None:
    """Replace SERVICE, and keep the query only when it names this service."""
    if not _METRIC.fullmatch(template):
        return None
    if f"{tag}:SERVICE" not in template:
        return None
    query = template.replace("SERVICE", scoped)
    if f"{tag}:{scoped}" not in query:
        return None
    return query


def _names_other_service(query: str, tag: str, scoped: str) -> bool:
    values = re.findall(rf"(?:^|[{{,]){re.escape(tag)}:([^{{}}\s,]+)", query)
    return not values or any(value != scoped for value in values)


def _metric_lines(series: list, tag: str, scoped: str, span: str) -> list[str]:
    lines = []
    for item in series:
        if len(lines) == _SERIES_LIMIT:
            break
        if not isinstance(item, dict):
            continue
        points = _points(item.get("pointlist"))
        if not points:
            continue
        name = item.get("metric")
        label = name if isinstance(name, str) and _METRIC_NAME.fullmatch(name) else "value"
        lines.append(
            f"datadog metric {tag}:{scoped} {label}: "
            f"last={_number(points[-1])} peak={_number(max(points))} during {span}."
        )
    return lines


def _points(raw: object) -> list[float]:
    if not isinstance(raw, list):
        return []
    points = []
    for row in raw:
        if not isinstance(row, (list, tuple)) or len(row) < 2:
            continue
        number = _count(row[1])
        if number is None:
            continue
        points.append(number)
    return points


def _count(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def _number(value: float) -> str:
    rounded = round(value, 4)
    if rounded == int(rounded):
        return str(int(rounded))
    return f"{rounded:.4f}".rstrip("0").rstrip(".")


def _missing(settings: Settings) -> str:
    if not _SITE.fullmatch(settings.datadog_site):
        return "DATADOG_SITE to a host such as datadoghq.com or datadoghq.eu"
    if not settings.datadog_api_key:
        return "DATADOG_API_KEY"
    if not settings.datadog_app_key:
        return "DATADOG_APP_KEY"
    return ""


def _limit(limit: int) -> int:
    if limit < 1:
        return 1
    return min(limit, 50)
