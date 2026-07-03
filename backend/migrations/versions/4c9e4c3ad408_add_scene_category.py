"""add_scene_category

Revision ID: 4c9e4c3ad408
Revises: e6f7a8b9c0d1
Create Date: 2026-07-03 12:50:35.031869
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "4c9e4c3ad408"
down_revision: str | None = "a384baa396e7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "scene_category",
        sa.Column("domain", sa.Text(), nullable=False),
        sa.Column("subcategory", sa.Text(), nullable=True),
        sa.Column("display_order", sa.Integer(), server_default="0"),
        sa.Column("org_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["org.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "org_id", "domain", "subcategory", name="uq_scene_category_org_domain_sub"
        ),
    )


def downgrade() -> None:
    op.drop_table("scene_category")
