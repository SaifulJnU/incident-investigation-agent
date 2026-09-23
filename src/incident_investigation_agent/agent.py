"""Build the Strands investigation agent for the configured model provider."""

from __future__ import annotations

from strands import Agent

from incident_investigation_agent.config import Settings
from incident_investigation_agent.case import CaseStore
from incident_investigation_agent.models import build_model
from incident_investigation_agent.prompts import SYSTEM_PROMPT
from incident_investigation_agent.tools import build_tools


def build_agent(settings: Settings, store=None) -> Agent:
    if store is None:
        store = CaseStore(settings.case_dir)
    return Agent(
        model=build_model(settings),
        tools=build_tools(store, settings.log_dir),
        system_prompt=SYSTEM_PROMPT,
    )
