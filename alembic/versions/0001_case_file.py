"""Case file tables."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001_case_file"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "incidents",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("service", sa.String(120), nullable=False),
        sa.Column("severity", sa.String(8), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "severity IN ('sev1', 'sev2', 'sev3', 'sev4')",
            name="ck_incident_severity",
        ),
        sa.CheckConstraint(
            "status IN ('open', 'investigating', 'mitigated', 'resolved')",
            name="ck_incident_status",
        ),
    )
    op.create_table(
        "evidence",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("incident_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("source", sa.String(200), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["incident_id"], ["incidents.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "kind IN ('symptom', 'log', 'timeline', 'change', 'hypothesis')",
            name="ck_evidence_kind",
        ),
    )
    op.create_index("ix_evidence_incident_id", "evidence", ["incident_id"])
    op.create_table(
        "investigation_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("incident_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("model_name", sa.String(512), nullable=False),
        sa.Column("report", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["incident_id"], ["incidents.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed')",
            name="ck_run_status",
        ),
    )
    op.create_index("ix_investigation_runs_incident_id", "investigation_runs", ["incident_id"])
    op.create_index("ix_investigation_runs_status", "investigation_runs", ["status"])
    op.create_index(
        "uq_incident_active_run",
        "investigation_runs",
        ["incident_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('queued', 'running')"),
    )


def downgrade() -> None:
    op.drop_index("uq_incident_active_run", table_name="investigation_runs")
    op.drop_index("ix_investigation_runs_status", table_name="investigation_runs")
    op.drop_index("ix_investigation_runs_incident_id", table_name="investigation_runs")
    op.drop_table("investigation_runs")
    op.drop_index("ix_evidence_incident_id", table_name="evidence")
    op.drop_table("evidence")
    op.drop_table("incidents")
