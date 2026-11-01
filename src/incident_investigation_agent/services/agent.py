"""The note call. Searches have already finished, so this agent has no tools."""

from __future__ import annotations

from strands import Agent

from incident_investigation_agent.core.config import Settings
from incident_investigation_agent.infrastructure.llm import build_model
from incident_investigation_agent.services.prompts import NOTE_PROMPT


def build_note_agent(settings: Settings) -> Agent:
    """One reply from searches that already finished. No tools, so no extra model round trips."""
    return Agent(model=build_model(settings, max_tokens=180), tools=[], system_prompt=NOTE_PROMPT)
