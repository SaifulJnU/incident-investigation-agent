"""Turn a case and a model result into the text the worker stores."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class IncidentBrief:
    title: str
    service: str
    severity: str
    summary: str
    started_at: datetime


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
    lines.append("Investigate and write the incident note.")
    return "\n".join(lines)


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
