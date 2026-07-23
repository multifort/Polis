"""Allow non-trigger and shared-trigger child bundle dependencies.

Revision ID: a1b2c3d4e5f6
Revises: 9d0e1f2a3b4c
Create Date: 2026-07-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: str | None = "9d0e1f2a3b4c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "definition_bundle_dependency",
        "trigger_key",
        existing_type=sa.Text(),
        nullable=True,
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE definition_bundle_dependency "
        "DISABLE TRIGGER trg_definition_bundle_dependency_immutable"
    )
    op.execute(
        sa.text(
            "UPDATE definition_bundle_dependency "
            "SET trigger_key = dependency_key WHERE trigger_key IS NULL"
        )
    )
    op.execute(
        "ALTER TABLE definition_bundle_dependency "
        "ENABLE TRIGGER trg_definition_bundle_dependency_immutable"
    )
    op.alter_column(
        "definition_bundle_dependency",
        "trigger_key",
        existing_type=sa.Text(),
        nullable=False,
    )
