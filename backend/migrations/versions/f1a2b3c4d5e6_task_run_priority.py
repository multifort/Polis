"""add task_run priority

Revision ID: f1a2b3c4d5e6
Revises: e7740a5badcb
Create Date: 2026-07-04 16:40:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f1a2b3c4d5e6"
down_revision: str | None = "e7740a5badcb"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "task_run",
        sa.Column("priority", sa.Integer(), server_default="0", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("task_run", "priority")
