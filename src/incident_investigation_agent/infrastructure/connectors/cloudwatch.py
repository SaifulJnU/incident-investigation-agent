"""Read CloudWatch Logs for the case service. Does not write log events."""

from __future__ import annotations

import re
import time

from strands import tool

from incident_investigation_agent.core.config import Settings
from incident_investigation_agent.infrastructure.connectors.mapping import (
    clean_query,
    mapped_target,
    require_service,
)

_GROUP = re.compile(r"^[\w./-]{1,512}$")


def logs_client(region: str, endpoint_url: str = ""):
    import boto3

    kwargs = {"region_name": region}
    if endpoint_url:
        kwargs["endpoint_url"] = endpoint_url
        kwargs["aws_access_key_id"] = "test"
        kwargs["aws_secret_access_key"] = "test"
    return boto3.client("logs", **kwargs)


def tools_for(settings: Settings, service: str | None):
    @tool
    def search_cloudwatch(query: str, limit: int = 20) -> str:
        """Search CloudWatch Logs for this case's service. Read-only.

        Args:
            query: A short word or phrase to find in the log group
            limit: Maximum events to return
        """
        return search_cloudwatch_logs(settings, service, query, limit)

    return [search_cloudwatch]


def search_cloudwatch_logs(settings: Settings, service: str | None, query: str, limit: int) -> str:
    scoped = require_service(service)
    if scoped is None:
        return "No service is set on this case, so CloudWatch was not searched."
    needle = clean_query(query)
    if needle is None:
        return "Query is empty or has characters CloudWatch search does not send."
    group = _log_group(settings, scoped)
    if group is None:
        return (
            "CloudWatch is not configured. Set CLOUDWATCH_LOG_GROUP_PREFIX "
            "or CLOUDWATCH_LOG_GROUPS."
        )
    capped = _limit(limit)
    start = int((time.time() - settings.cloudwatch_lookback_minutes * 60) * 1000)
    try:
        client = logs_client(settings.aws_region, settings.aws_endpoint_url)
        page = client.filter_log_events(
            logGroupName=group,
            filterPattern=needle if " " not in needle else f'"{needle}"',
            startTime=start,
            limit=capped,
        )
    except Exception as exc:
        return f"CloudWatch search failed for {group}: {_safe_error(exc)}"
    events = page.get("events") or []
    if not events:
        return (
            f"No CloudWatch events matched {needle!r} in {group} "
            f"during the last {settings.cloudwatch_lookback_minutes} minutes."
        )
    lines = []
    for event in events[:capped]:
        message = str(event.get("message", "")).strip().replace("\n", " ")
        lines.append(f"{group}: {message[:500]}")
    return "\n".join(lines)


def _log_group(settings: Settings, service: str) -> str | None:
    group = mapped_target(settings.cloudwatch_log_groups, service)
    if not group and settings.cloudwatch_log_group_prefix:
        group = f"{settings.cloudwatch_log_group_prefix}{service}"
    if not group or ".." in group or not _GROUP.fullmatch(group):
        return None
    return group


def _limit(limit: int) -> int:
    if limit < 1:
        return 1
    return min(limit, 50)


def _safe_error(exc: Exception) -> str:
    text = str(exc).splitlines()[0][:300]
    return text or exc.__class__.__name__
