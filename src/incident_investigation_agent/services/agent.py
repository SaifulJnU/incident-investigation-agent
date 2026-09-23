"""Build the Strands investigation agent for the configured model provider."""

from __future__ import annotations

from strands import Agent

from incident_investigation_agent.core.config import Settings
from incident_investigation_agent.domain.evidence import EvidenceStore
from incident_investigation_agent.infrastructure.file_case import CaseStore
from incident_investigation_agent.infrastructure.llm import build_model
from incident_investigation_agent.infrastructure.tools import build_tools
from incident_investigation_agent.services.prompts import SYSTEM_PROMPT


def build_agent(settings: Settings, store: EvidenceStore | None = None) -> Agent:
    if store is None:
        store = CaseStore(settings.case_dir)
    return Agent(
        model=build_model(settings),
        tools=build_tools(store, settings.log_dir),
        system_prompt=SYSTEM_PROMPT,
    )
