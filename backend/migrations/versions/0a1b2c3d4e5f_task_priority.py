"""add task priority

Revision ID: 0a1b2c3d4e5f
Revises: f1a2b3c4d5e6
Create Date: 2026-07-04 17:20:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0a1b2c3d4e5f"
down_revision: str | None = "f1a2b3c4d5e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "task",
        sa.Column("priority", sa.Integer(), server_default="0", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("task", "priority")
