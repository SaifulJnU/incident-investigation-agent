"""Call one read-only tool on a company MCP server. Does not write back."""

from __future__ import annotations

import json
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from strands import tool

from incident_investigation_agent.core.config import Settings
from incident_investigation_agent.infrastructure.connectors.http import ConnectorError
from incident_investigation_agent.infrastructure.connectors.mapping import (
    clean_query,
    mapped_target,
    require_service,
)
from incident_investigation_agent.infrastructure.redact import configured_secrets, redact

_URL = re.compile(
    r"^https://[A-Za-z0-9.-]+(?::[0-9]+)?(?:/[A-Za-z0-9._~:/?#\[\]@!$&'()*+,;=%-]*)?$"
)
_LOCAL = re.compile(r"^http://(?:127\.0\.0\.1|localhost)(?::[0-9]+)?(?:/.*)?$")
_TOOL = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,80}$")
_WRITE = frozenset(
    {
        "commit",
        "push",
        "restart",
        "rollback",
        "delete",
        "remove",
        "write",
        "create",
        "update",
        "execute",
        "shell",
        "deploy",
    }
)


def tools_for(settings: Settings, service: str | None):
    @tool
    def search_mcp_tool(query: str, limit: int = 20) -> str:
        """Call this case's allowlisted MCP tool. Read-only.

        Args:
            query: A short word to pass to the tool
            limit: Maximum text blocks to keep
        """
        return search_mcp(settings, service, query, limit)

    return [search_mcp_tool]


def search_mcp(settings: Settings, service: str | None, query: str, limit: int) -> str:
    scoped = require_service(service)
    if scoped is None:
        return "No service is set on this case, so MCP was not searched."
    needle = clean_query(query)
    if needle is None:
        return "Query is empty or has characters MCP search does not send."
    url = _url(settings.mcp_url)
    if url is None:
        return "MCP is not configured. Set MCP_URL to an https MCP endpoint."
    chosen = _tool_for(settings.mcp_tools, scoped)
    if chosen is None:
        return "MCP has no tool for this service. Set MCP_TOOLS to service=tool pairs."
    if not _read_only(chosen):
        return f"MCP tool {chosen} is not read-only, so it was not called."
    if _names_other_service(chosen, scoped, settings.mcp_tools):
        return f"MCP tool {chosen} reads another service, so it was not called."
    secrets = configured_secrets(settings)
    headers = {"Accept": "application/json, text/event-stream"}
    if settings.mcp_token:
        headers["Authorization"] = f"Bearer {settings.mcp_token}"
    timeout = settings.connector_timeout_seconds
    try:
        _, session = _exchange(
            url,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "case-file", "version": "0.1.0"},
                },
            },
            headers,
            timeout,
            secrets,
        )
        if session:
            headers["Mcp-Session-Id"] = session
        _exchange(
            url,
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            headers,
            timeout,
            secrets,
        )
        body, _ = _exchange(
            url,
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": chosen,
                    "arguments": {"query": needle, "service": scoped, "limit": _limit(limit)},
                },
            },
            headers,
            timeout,
            secrets,
        )
    except ConnectorError as exc:
        return f"MCP search failed for {chosen}: {exc}"
    text = _text(body, _limit(limit))
    if not text:
        return f"MCP returned no text for {chosen}."
    return redact(text, secrets)


def _tool_for(raw: str, service: str) -> str | None:
    name = mapped_target(raw, service)
    if not name or not _TOOL.fullmatch(name):
        return None
    return name


def _read_only(name: str) -> bool:
    parts = re.split(r"[^A-Za-z]+", name.lower())
    return not any(part in _WRITE for part in parts)


def _names_other_service(tool: str, service: str, raw: str) -> bool:
    folded = tool.lower().replace("-", "").replace("_", "")
    current = {service.lower().replace("-", "").replace("_", "")}
    current.update(part for part in re.split(r"[^a-z0-9]+", service.lower()) if len(part) >= 4)
    for entry in raw.split(","):
        key = entry.split("=", 1)[0].strip().lower()
        if not key or key == service.lower():
            continue
        for piece in re.split(r"[^a-z0-9]+", key):
            if len(piece) < 4 or piece in current:
                continue
            if piece in folded:
                return True
    return False


def _url(raw: str) -> str | None:
    text = raw.strip().rstrip("/")
    if _URL.fullmatch(text) or _LOCAL.fullmatch(text):
        return text
    return None


def _limit(limit: int) -> int:
    if limit < 1:
        return 1
    return min(limit, 20)


def _exchange(url: str, payload: dict, headers: dict[str, str], timeout: float, secrets: tuple[str, ...]):
    data = json.dumps(payload).encode("utf-8")
    req_headers = {"Content-Type": "application/json", "User-Agent": "case-file", **headers}
    request = Request(url, data=data, headers=req_headers, method="POST")
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read()
            session = str(response.headers.get("Mcp-Session-Id") or "")
    except HTTPError as exc:
        detail = redact(exc.read().decode("utf-8", errors="replace")[:300], (*secrets, *req_headers.values()))
        raise ConnectorError(f"HTTP {exc.code}. {detail}") from None
    except URLError as exc:
        reason = redact(str(exc.reason), secrets)
        raise ConnectorError(f"Could not reach the service ({reason}).") from None
    if not raw:
        return {}, session
    try:
        body = _parse(raw)
    except (json.JSONDecodeError, ValueError):
        raise ConnectorError("The service returned a response that was not JSON.") from None
    if isinstance(body, dict) and body.get("error"):
        error = body["error"]
        message = error.get("message") if isinstance(error, dict) else error
        raise ConnectorError(redact(str(message), secrets)[:300])
    return body, session


def _parse(raw: bytes) -> object:
    text = raw.decode("utf-8", errors="replace").strip()
    if text.startswith("{") or text.startswith("["):
        return json.loads(text)
    messages = []
    for line in text.splitlines():
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data and data != "[DONE]":
            messages.append(json.loads(data))
    if not messages:
        raise ValueError("no JSON")
    return messages[-1]


def _text(body: object, limit: int) -> str:
    if not isinstance(body, dict):
        return ""
    result = body.get("result")
    if not isinstance(result, dict) or result.get("isError"):
        return ""
    content = result.get("content")
    if isinstance(content, str):
        return content.strip()[:2000]
    if not isinstance(content, list):
        return ""
    lines = []
    for block in content:
        if not isinstance(block, dict) or block.get("type") not in (None, "text"):
            continue
        line = str(block.get("text") or "").strip()
        if line:
            lines.append(line.replace("\n", " ")[:500])
        if len(lines) >= limit:
            break
    return "\n".join(lines)
