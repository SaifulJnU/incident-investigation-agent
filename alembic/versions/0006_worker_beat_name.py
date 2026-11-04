"""Let each worker process store its own heartbeat name."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006_worker_beat_name"
down_revision = "0005_status_history"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "worker_beats",
        "name",
        existing_type=sa.String(length=32),
        type_=sa.String(length=128),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "worker_beats",
        "name",
        existing_type=sa.String(length=128),
        type_=sa.String(length=32),
        existing_nullable=False,
    )
