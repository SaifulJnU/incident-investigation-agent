"""Tools the agent uses to record a case and search local logs."""

from __future__ import annotations

from pathlib import Path

from strands import tool

from incident_investigation_agent.case import CaseStore
from incident_investigation_agent.logs import search_logs as search_log_files

EVIDENCE_KINDS = {"symptom", "log", "timeline", "change", "hypothesis"}


def build_tools(store: CaseStore, log_dir: Path):
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

    @tool
    def search_logs(query: str, limit: int = 20) -> str:
        """Search text logs for a case-insensitive substring.

        Args:
            query: Text to find in the configured log directory
            limit: Maximum matching lines to return
        """
        return search_log_files(log_dir, query, limit)

    return [record_evidence, list_evidence, search_logs]
