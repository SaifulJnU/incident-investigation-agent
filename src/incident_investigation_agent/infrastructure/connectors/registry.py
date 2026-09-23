"""Turn APP_ENV and CONNECTORS into the tool list for one investigation."""

from __future__ import annotations

from incident_investigation_agent.core.config import Settings, enabled_connectors
from incident_investigation_agent.infrastructure.connectors import (
    cloudwatch,
    datadog,
    github,
    local_logs,
    loki,
)

_FACTORIES = {
    "local_logs": local_logs.tools_for,
    "cloudwatch": cloudwatch.tools_for,
    "datadog": datadog.tools_for,
    "loki": loki.tools_for,
    "github": github.tools_for,
}


def connector_tools(settings: Settings, service: str | None):
    tools = []
    for name in enabled_connectors(settings.app_env, settings.connectors):
        tools.extend(_FACTORIES[name](settings, service))
    return tools
