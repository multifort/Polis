"""result_envelope 黑板：加 content(全文) + tokens（V2-B1）

Revision ID: 9a1b2c3d4e5f
Revises: 31dfc5245d2f
Create Date: 2026-06-22 21:00:00.000000

向后兼容：两列均 nullable，旧行 content 为空时读侧回退 summary。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "9a1b2c3d4e5f"
down_revision: str | None = "31dfc5245d2f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("result_envelope", sa.Column("content", sa.Text(), nullable=True))
    op.add_column("result_envelope", sa.Column("tokens", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("result_envelope", "tokens")
    op.drop_column("result_envelope", "content")
