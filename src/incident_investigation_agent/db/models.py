"""Postgres records for a case file. The agent writes evidence; people close the case."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    Uuid,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Incident(Base):
    __tablename__ = "incidents"
    __table_args__ = (
        CheckConstraint(
            "severity IN ('sev1', 'sev2', 'sev3', 'sev4')",
            name="ck_incident_severity",
        ),
        CheckConstraint(
            "status IN ('open', 'investigating', 'mitigated', 'resolved')",
            name="ck_incident_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(200))
    summary: Mapped[str] = mapped_column(Text())
    service: Mapped[str] = mapped_column(String(120))
    severity: Mapped[str] = mapped_column(String(8))
    status: Mapped[str] = mapped_column(String(20), default="open")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    opened_by: Mapped[str] = mapped_column(String(200), default="")


class EvidenceItem(Base):
    __tablename__ = "evidence"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('symptom', 'log', 'timeline', 'change', 'hypothesis')",
            name="ck_evidence_kind",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    incident_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("incidents.id", ondelete="CASCADE"),
        index=True,
    )
    kind: Mapped[str] = mapped_column(String(20))
    summary: Mapped[str] = mapped_column(Text())
    source: Mapped[str] = mapped_column(String(200), default="operator")
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class InvestigationRun(Base):
    __tablename__ = "investigation_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed')",
            name="ck_run_status",
        ),
        Index(
            "uq_incident_active_run",
            "incident_id",
            unique=True,
            postgresql_where=text("status IN ('queued', 'running')"),
            sqlite_where=text("status IN ('queued', 'running')"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    incident_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("incidents.id", ondelete="CASCADE"),
        index=True,
    )
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    provider: Mapped[str] = mapped_column(String(32), default="")
    model_name: Mapped[str] = mapped_column(String(512), default="")
    requested_by: Mapped[str] = mapped_column(String(200), default="")
    report: Mapped[str | None] = mapped_column(Text(), nullable=True)
    error: Mapped[str | None] = mapped_column(Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
