"""Case-file tools, plus the connectors selected by APP_ENV."""

from __future__ import annotations

from strands import tool

from incident_investigation_agent.core.config import Settings
from incident_investigation_agent.domain.evidence import EVIDENCE_KINDS, EvidenceStore
from incident_investigation_agent.infrastructure.connectors.registry import connector_tools


def build_tools(store: EvidenceStore, settings: Settings, service: str | None = None):
    @tool
    def record_evidence(kind: str, summary: str, source: str = "operator") -> str:
        """Record a fact gathered during the investigation.

        Args:
            kind: One of symptom, log, timeline, change, hypothesis
            summary: What was observed, in one or two sentences
            source: Where the fact came from
        """
        normalized = kind.strip().lower()
        if normalized not in EVIDENCE_KINDS:
            allowed = ", ".join(sorted(EVIDENCE_KINDS))
            return f"Unknown evidence kind {kind!r}. Use one of: {allowed}."
        if not summary.strip():
            return "Summary is empty. Nothing was recorded."
        item = store.add(normalized, summary, source)
        return f"Recorded {item.kind} from {item.source}: {item.summary}"

    @tool
    def list_evidence() -> str:
        """List evidence recorded so far for this incident."""
        items = store.list()
        if not items:
            return "No evidence recorded yet."
        lines = [
            f"- [{item.kind}] {item.summary} (source: {item.source})"
            for item in items
        ]
        return "\n".join(lines)

    return [record_evidence, list_evidence, *connector_tools(settings, service)]
