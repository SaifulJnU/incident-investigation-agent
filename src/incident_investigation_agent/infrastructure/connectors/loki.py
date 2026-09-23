"""Read Grafana Loki for the case service. Does not push log streams."""

from __future__ import annotations

import time
from urllib.parse import urlencode

from strands import tool

from incident_investigation_agent.core.config import Settings
from incident_investigation_agent.infrastructure.connectors.http import ConnectorError, request_json
from incident_investigation_agent.infrastructure.connectors.mapping import (
    clean_query,
    require_label,
    require_service,
)


def tools_for(settings: Settings, service: str | None):
    @tool
    def search_loki(query: str, limit: int = 20) -> str:
        """Search Loki for this case's service. Read-only.

        Args:
            query: A short word to find in log lines for this service
            limit: Maximum lines to return
        """
        return search_loki_logs(settings, service, query, limit)

    return [search_loki]


def search_loki_logs(settings: Settings, service: str | None, query: str, limit: int) -> str:
    scoped = require_service(service)
    if scoped is None:
        return "No service is set on this case, so Loki was not searched."
    needle = clean_query(query)
    if needle is None:
        return "Query is empty or has characters Loki search does not send."
    base = _base_url(settings.loki_url)
    if base is None:
        return "Loki is not configured. Set LOKI_URL to the Loki base URL, such as https://loki.example.com."
    label = require_label(settings.loki_label)
    if label is None:
        return "LOKI_LABEL must be a label name such as service."
    capped = _limit(limit)
    escaped = needle.replace("\\", "\\\\").replace('"', '\\"')
    logql = f'{{{label}="{scoped}"}} |= "{escaped}"'
    end_ns = time.time_ns()
    start_ns = end_ns - settings.loki_lookback_minutes * 60 * 1_000_000_000
    url = f"{base}/loki/api/v1/query_range?{urlencode({'query': logql, 'start': start_ns, 'end': end_ns, 'limit': capped})}"
    headers = {}
    if settings.loki_token:
        headers["Authorization"] = f"Bearer {settings.loki_token}"
    try:
        body = request_json(url, headers=headers)
    except ConnectorError as exc:
        return f"Loki search failed: {exc}"
    return _lines(body, label, scoped, needle, settings.loki_lookback_minutes, capped)


def _base_url(raw: str) -> str | None:
    url = raw.strip().rstrip("/")
    if not url.startswith(("https://", "http://")):
        return None
    if "@" in url.split("://", 1)[1]:
        return None
    return url


def _lines(body: object, label: str, service: str, needle: str, minutes: int, limit: int) -> str:
    data = body.get("data") if isinstance(body, dict) else None
    result = data.get("result") if isinstance(data, dict) else None
    lines: list[str] = []
    if isinstance(result, list):
        for stream in result:
            values = stream.get("values") if isinstance(stream, dict) else None
            if not isinstance(values, list):
                continue
            for value in values:
                if isinstance(value, list) and len(value) >= 2:
                    text = str(value[1]).strip().replace("\n", " ")
                    if text:
                        lines.append(f"loki {label}={service}: {text[:500]}")
                if len(lines) >= limit:
                    break
    if not lines:
        return (
            f"No Loki lines matched {needle!r} for {label}={service} "
            f"during the last {minutes} minutes."
        )
    return "\n".join(lines[:limit])


def _limit(limit: int) -> int:
    if limit < 1:
        return 1
    return min(limit, 50)
