"""memory 晋升溯源：加 promoted_from + last_promoted_at（V2-B3）

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
Create Date: 2026-06-27 22:30:00.000000

向后兼容：两列均 nullable。promoted_from = 晋升来源（task_run / envelope 等）溯源；
last_promoted_at = 该来源最近被晋升的时间（幂等：不重复晋升同一来源）。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d5e6f7a8b9c0"
down_revision: str | None = "c4d5e6f7a8b9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "memory",
        sa.Column("promoted_from", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "memory",
        sa.Column("last_promoted_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("memory", "last_promoted_at")
    op.drop_column("memory", "promoted_from")
