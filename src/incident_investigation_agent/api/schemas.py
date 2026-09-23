"""Request and response bodies for the case file API."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

Severity = Literal["sev1", "sev2", "sev3", "sev4"]
Status = Literal["open", "investigating", "mitigated", "resolved"]
EvidenceKind = Literal["symptom", "log", "timeline", "change", "hypothesis"]
RunStatus = Literal["queued", "running", "completed", "failed"]


def _blank(value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError("must not be blank")
    return cleaned


class IncidentCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    service: str = Field(min_length=1, max_length=120)
    summary: str = Field(min_length=1)
    severity: Severity
    started_at: datetime | None = None

    @field_validator("title", "service", "summary")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return _blank(value)


class IncidentPatch(BaseModel):
    status: Status | None = None
    severity: Severity | None = None
    summary: str | None = None

    @field_validator("summary")
    @classmethod
    def strip_summary(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _blank(value)


class EvidenceCreate(BaseModel):
    kind: EvidenceKind
    summary: str = Field(min_length=1)

    @field_validator("summary")
    @classmethod
    def strip_summary(cls, value: str) -> str:
        return _blank(value)


class EvidenceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    kind: EvidenceKind
    summary: str
    source: str
    recorded_at: datetime


class RunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    status: RunStatus
    provider: str
    model_name: str
    report: str | None
    error: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class IncidentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    summary: str
    service: str
    severity: Severity
    status: Status
    started_at: datetime
    created_at: datetime
    updated_at: datetime


class IncidentDetail(IncidentOut):
    evidence: list[EvidenceOut]
    runs: list[RunOut]
