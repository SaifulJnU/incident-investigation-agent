"""Record the engineer's name, and who mitigated or resolved a case."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003_case_actors"
down_revision = "0002_actors"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("incidents", sa.Column("opened_by_name", sa.String(200), nullable=False, server_default=""))
    op.add_column("incidents", sa.Column("mitigated_by", sa.String(200), nullable=False, server_default=""))
    op.add_column("incidents", sa.Column("mitigated_by_name", sa.String(200), nullable=False, server_default=""))
    op.add_column("incidents", sa.Column("mitigated_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("incidents", sa.Column("resolved_by", sa.String(200), nullable=False, server_default=""))
    op.add_column("incidents", sa.Column("resolved_by_name", sa.String(200), nullable=False, server_default=""))
    op.add_column("incidents", sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "investigation_runs",
        sa.Column("requested_by_name", sa.String(200), nullable=False, server_default=""),
    )
    op.create_index("ix_incidents_status", "incidents", ["status"])
    op.alter_column("incidents", "opened_by_name", server_default=None)
    op.alter_column("incidents", "mitigated_by", server_default=None)
    op.alter_column("incidents", "mitigated_by_name", server_default=None)
    op.alter_column("incidents", "resolved_by", server_default=None)
    op.alter_column("incidents", "resolved_by_name", server_default=None)
    op.alter_column("investigation_runs", "requested_by_name", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_incidents_status", table_name="incidents")
    op.drop_column("investigation_runs", "requested_by_name")
    op.drop_column("incidents", "resolved_at")
    op.drop_column("incidents", "resolved_by_name")
    op.drop_column("incidents", "resolved_by")
    op.drop_column("incidents", "mitigated_at")
    op.drop_column("incidents", "mitigated_by_name")
    op.drop_column("incidents", "mitigated_by")
    op.drop_column("incidents", "opened_by_name")
