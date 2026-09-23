"""Search the log folder. This is the connector used when APP_ENV is local."""

from __future__ import annotations

from strands import tool

from incident_investigation_agent.core.config import Settings
from incident_investigation_agent.infrastructure.connectors.mapping import require_service
from incident_investigation_agent.infrastructure.logs import scoped_log_dir, search_logs


def tools_for(settings: Settings, service: str | None):
    @tool(name="search_logs")
    def search_logs_tool(query: str, limit: int = 20) -> str:
        """Search this case's log files for a short case-insensitive word.

        Args:
            query: A short word such as timeout or 500
            limit: Maximum matching lines
        """
        return search_local_logs(settings, service, query, limit)

    return [search_logs_tool]


def search_local_logs(settings: Settings, service: str | None, query: str, limit: int) -> str:
    directory = settings.log_dir
    if service is not None:
        scoped = require_service(service)
        if scoped is None:
            return f"Invalid service name {service!r}. Local logs were not searched."
        directory = scoped_log_dir(settings.log_dir, scoped)
    return search_logs(directory, query, limit)
