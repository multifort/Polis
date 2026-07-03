"""merge_scene_category

Revision ID: e7740a5badcb
Revises: 4c9e4c3ad408, e6f7a8b9c0d1
Create Date: 2026-07-03 12:51:16.075667
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e7740a5badcb"
down_revision: str | None = ("4c9e4c3ad408", "e6f7a8b9c0d1")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
