"""baseline (empty)

Revision ID: 23b806311f63
Revises:
Create Date: 2026-06-18 10:15:31.023929
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "23b806311f63"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
