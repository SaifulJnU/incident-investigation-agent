"""Record when the worker last showed it was alive."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004_worker_beat"
down_revision = "0003_case_actors"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "worker_beats",
        sa.Column("name", sa.String(32), primary_key=True),
        sa.Column("beat_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("worker_beats")
