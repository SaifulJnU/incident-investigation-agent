"""HTTP JSON for read-only connectors. Secrets stay in request headers."""

from __future__ import annotations

import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class ConnectorError(Exception):
    """A connector call failed. The message is safe to show the model."""


def request_json(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    payload: dict | None = None,
    timeout: float = 15,
) -> object:
    data = None
    req_headers = {"Accept": "application/json", "User-Agent": "case-file"}
    if headers:
        req_headers.update(headers)
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        req_headers["Content-Type"] = "application/json"
    request = Request(url, data=data, headers=req_headers, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        raise ConnectorError(f"HTTP {exc.code}. {detail}") from None
    except URLError as exc:
        raise ConnectorError(f"Could not reach the service ({exc.reason}).") from None
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        raise ConnectorError("The service returned a response that was not JSON.") from None
