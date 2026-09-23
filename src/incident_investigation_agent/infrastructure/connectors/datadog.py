"""Read Datadog logs for the case service. Does not post events or metrics."""

from __future__ import annotations

import re

from strands import tool

from incident_investigation_agent.core.config import Settings
from incident_investigation_agent.infrastructure.connectors.http import ConnectorError, request_json
from incident_investigation_agent.infrastructure.connectors.mapping import clean_query, require_service

_SITE = re.compile(r"^[a-z0-9][a-z0-9.-]{0,200}$")
_TAG = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def tools_for(settings: Settings, service: str | None):
    @tool
    def search_datadog(query: str, limit: int = 20) -> str:
        """Search Datadog logs for this case's service. Read-only.

        Args:
            query: A short word to find, combined with the service tag
            limit: Maximum log events to return
        """
        return search_datadog_logs(settings, service, query, limit)

    return [search_datadog]


def search_datadog_logs(settings: Settings, service: str | None, query: str, limit: int) -> str:
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
    url = f"https://api.{settings.datadog_site}/api/v2/logs/events/search"
    payload = {
        "filter": {
            "query": f"{tag}:{scoped} {needle}",
            "from": f"now-{settings.datadog_lookback_minutes}m",
            "to": "now",
        },
        "page": {"limit": capped},
        "sort": "-timestamp",
    }
    headers = {
        "DD-API-KEY": settings.datadog_api_key,
        "DD-APPLICATION-KEY": settings.datadog_app_key,
    }
    try:
        body = request_json(url, method="POST", headers=headers, payload=payload)
    except ConnectorError as exc:
        return f"Datadog search failed: {exc}"
    rows = body.get("data") if isinstance(body, dict) else None
    if not rows:
        return (
            f"No Datadog logs matched {needle!r} for {tag}:{scoped} "
            f"during the last {settings.datadog_lookback_minutes} minutes."
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
