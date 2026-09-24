"""Build the Strands investigation agent for the configured model provider."""

from __future__ import annotations

from strands import Agent

from incident_investigation_agent.core.config import Settings, enabled_connectors
from incident_investigation_agent.domain.evidence import EvidenceStore
from incident_investigation_agent.infrastructure.file_case import CaseStore
from incident_investigation_agent.infrastructure.llm import build_model
from incident_investigation_agent.infrastructure.tools import build_tools
from incident_investigation_agent.services.prompts import NOTE_PROMPT, SYSTEM_PROMPT


def build_agent(
    settings: Settings,
    store: EvidenceStore | None = None,
    service: str | None = None,
) -> Agent:
    if store is None:
        store = CaseStore(settings.case_dir)
    names = ", ".join(enabled_connectors(settings.app_env, settings.connectors))
    return Agent(
        model=build_model(settings),
        tools=build_tools(store, settings, service),
        system_prompt=SYSTEM_PROMPT + f"\nConnectors enabled for this run: {names}.\n",
    )


def build_note_agent(settings: Settings) -> Agent:
    """One reply from searches that already finished. No tools, so no extra model round trips."""
    return Agent(model=build_model(settings, max_tokens=180), tools=[], system_prompt=NOTE_PROMPT)
