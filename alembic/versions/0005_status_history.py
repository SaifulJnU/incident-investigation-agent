"""Keep each status edit, not only the latest actor on the case."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005_status_history"
down_revision = "0004_worker_beat"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "status_changes",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("incident_id", sa.Uuid(), nullable=False),
        sa.Column("from_status", sa.String(20), nullable=True),
        sa.Column("to_status", sa.String(20), nullable=False),
        sa.Column("actor", sa.String(200), nullable=False),
        sa.Column("actor_name", sa.String(200), nullable=False),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "from_status IS NULL OR from_status IN ('open', 'investigating', 'mitigated', 'resolved')",
            name="ck_status_change_from",
        ),
        sa.CheckConstraint(
            "to_status IN ('open', 'investigating', 'mitigated', 'resolved')",
            name="ck_status_change_to",
        ),
        sa.ForeignKeyConstraint(["incident_id"], ["incidents.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_status_changes_incident_id", "status_changes", ["incident_id"])


def downgrade() -> None:
    op.drop_index("ix_status_changes_incident_id", table_name="status_changes")
    op.drop_table("status_changes")
