"""Read and write the case file stored in Postgres."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from incident_investigation_agent.case import Evidence
from incident_investigation_agent.schema import EvidenceItem, Incident, InvestigationRun, utcnow


ACTIVE_RUN = ("queued", "running")


class DbCaseStore:
    """Same add/list surface as the CLI case file, backed by Postgres."""

    def __init__(self, factory: sessionmaker[Session], incident_id: uuid.UUID) -> None:
        self.factory = factory
        self.incident_id = incident_id

    def add(self, kind: str, summary: str, source: str) -> Evidence:
        with self.factory() as session:
            item = EvidenceItem(
                incident_id=self.incident_id,
                kind=kind.strip().lower(),
                summary=summary.strip(),
                source=(source or "operator").strip(),
                recorded_at=utcnow(),
            )
            session.add(item)
            session.commit()
            return _evidence(item)

    def list(self) -> list[Evidence]:
        with self.factory() as session:
            rows = session.scalars(
                select(EvidenceItem)
                .where(EvidenceItem.incident_id == self.incident_id)
                .order_by(EvidenceItem.recorded_at)
            ).all()
            return [_evidence(row) for row in rows]


def list_incidents(session: Session) -> list[Incident]:
    return list(
        session.scalars(select(Incident).order_by(Incident.started_at.desc())).all()
    )


def get_incident(session: Session, incident_id: uuid.UUID) -> Incident | None:
    return session.get(Incident, incident_id)


def evidence_for(session: Session, incident_id: uuid.UUID) -> list[EvidenceItem]:
    return list(
        session.scalars(
            select(EvidenceItem)
            .where(EvidenceItem.incident_id == incident_id)
            .order_by(EvidenceItem.recorded_at)
        ).all()
    )


def runs_for(session: Session, incident_id: uuid.UUID) -> list[InvestigationRun]:
    return list(
        session.scalars(
            select(InvestigationRun)
            .where(InvestigationRun.incident_id == incident_id)
            .order_by(InvestigationRun.created_at.desc())
        ).all()
    )


def active_run(session: Session, incident_id: uuid.UUID) -> InvestigationRun | None:
    return session.scalars(
        select(InvestigationRun)
        .where(
            InvestigationRun.incident_id == incident_id,
            InvestigationRun.status.in_(ACTIVE_RUN),
        )
        .limit(1)
    ).first()


def open_incident(
    session: Session,
    *,
    title: str,
    summary: str,
    service: str,
    severity: str,
    started_at: datetime,
) -> Incident:
    incident = Incident(
        title=title,
        summary=summary,
        service=service,
        severity=severity,
        status="open",
        started_at=started_at,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    session.add(incident)
    session.flush()
    return incident


def add_evidence(
    session: Session,
    incident_id: uuid.UUID,
    *,
    kind: str,
    summary: str,
    source: str,
) -> EvidenceItem:
    item = EvidenceItem(
        incident_id=incident_id,
        kind=kind,
        summary=summary,
        source=source,
        recorded_at=utcnow(),
    )
    session.add(item)
    session.flush()
    return item


def queue_run(
    session: Session,
    incident: Incident,
    *,
    provider: str,
    model_name: str,
) -> InvestigationRun:
    run = InvestigationRun(
        incident_id=incident.id,
        status="queued",
        provider=provider,
        model_name=model_name,
        created_at=utcnow(),
    )
    session.add(run)
    session.flush()
    return run


def _evidence(item: EvidenceItem) -> Evidence:
    recorded = item.recorded_at
    stamp = recorded.isoformat() if isinstance(recorded, datetime) else str(recorded)
    return Evidence(
        kind=item.kind,
        summary=item.summary,
        source=item.source,
        recorded_at=stamp,
    )
