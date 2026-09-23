"""Map a case service name to a log group, query label, or repository."""

from __future__ import annotations

import re

_SERVICE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,118}$")
_LABEL = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_QUERY = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ._:/=+\-]{0,199}$")


def require_service(service: str | None) -> str | None:
    if service and _SERVICE.fullmatch(service):
        return service
    return None


def mapped_target(raw: str, service: str) -> str:
    """Read `service=target` pairs. An unknown service returns an empty string."""
    for entry in raw.split(","):
        entry = entry.strip()
        if "=" not in entry:
            continue
        key, value = entry.split("=", 1)
        if key.strip() == service and value.strip():
            return value.strip()
    return ""


def clean_query(query: str) -> str | None:
    text = " ".join(query.split())
    if _QUERY.fullmatch(text):
        return text
    return None


def require_label(label: str) -> str | None:
    if _LABEL.fullmatch(label):
        return label
    return None
