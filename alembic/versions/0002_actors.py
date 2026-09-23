"""Record who opened a case and who requested an investigation."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002_actors"
down_revision = "0001_case_file"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "incidents",
        sa.Column("opened_by", sa.String(200), nullable=False, server_default=""),
    )
    op.add_column(
        "investigation_runs",
        sa.Column("requested_by", sa.String(200), nullable=False, server_default=""),
    )
    op.alter_column("incidents", "opened_by", server_default=None)
    op.alter_column("investigation_runs", "requested_by", server_default=None)


def downgrade() -> None:
    op.drop_column("investigation_runs", "requested_by")
    op.drop_column("incidents", "opened_by")
