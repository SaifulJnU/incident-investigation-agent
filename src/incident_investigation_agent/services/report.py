"""Turn a case and a model result into the text the worker stores."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class IncidentBrief:
    title: str
    service: str
    severity: str
    summary: str
    started_at: datetime


# The worker strips this line before the note call. Gather still sees the brief above it.
BRIEF_TAIL = "Searches run before this note is written."


def investigation_prompt(brief: IncidentBrief, evidence: list) -> str:
    lines = [
        f"Incident: {brief.title}",
        f"Service: {brief.service}",
        f"Severity: {brief.severity}",
        f"Started: {brief.started_at.isoformat()}",
        f"What we know: {brief.summary}",
    ]
    if evidence:
        lines.append("Evidence already recorded:")
        for item in evidence:
            lines.append(f"- [{item.kind}] {item.summary} (source: {item.source})")
    lines.append(BRIEF_TAIL)
    return "\n".join(lines)


def case_started_at(prompt: str) -> datetime | None:
    """Read the ``Started:`` line the worker writes. A brief without one has no case time.

    Only the brief is read. A note added later cannot move the window.
    """
    head = prompt.split(BRIEF_TAIL)[0] if BRIEF_TAIL in prompt else prompt
    for line in head.splitlines():
        if not line.startswith("Started:"):
            continue
        raw = line.split(":", 1)[1].strip()
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed
    return None


def message_text(result: object) -> str:
    message = getattr(result, "message", None)
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            return content.strip()
        if isinstance(content, list):
            parts = [
                str(block.get("text", "")).strip()
                for block in content
                if isinstance(block, dict) and str(block.get("text", "")).strip()
            ]
            if parts:
                return "\n".join(parts)
    text = str(result).strip()
    if text:
        return text
    raise RuntimeError("The model returned an empty note.")
