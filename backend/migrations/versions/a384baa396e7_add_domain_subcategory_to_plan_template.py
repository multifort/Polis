"""add_domain_subcategory_to_plan_template

Revision ID: a384baa396e7
Revises: d5e6f7a8b9c0
Create Date: 2026-07-02 17:54:19.417995
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a384baa396e7"
down_revision: str | None = "d5e6f7a8b9c0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("plan_template", sa.Column("domain", sa.Text(), nullable=True))
    op.add_column("plan_template", sa.Column("subcategory", sa.Text(), nullable=True))
    op.add_column("plan_template", sa.Column("acceptance_criteria", sa.Text(), nullable=True))
    op.add_column("plan_template", sa.Column("source", sa.Text(), server_default="builtin"))


def downgrade() -> None:
    op.drop_column("plan_template", "source")
    op.drop_column("plan_template", "acceptance_criteria")
    op.drop_column("plan_template", "subcategory")
    op.drop_column("plan_template", "domain")
