"""role_template asset layer

Revision ID: e6f7a8b9c0d1
Revises: a384baa396e7
Create Date: 2026-07-03 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import pgvector.sqlalchemy
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e6f7a8b9c0d1"
down_revision: str | None = "a384baa396e7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "role_template",
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("version", sa.Text(), server_default="1.0", nullable=False),
        sa.Column("persona", sa.Text(), nullable=False),
        sa.Column(
            "skill_refs",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("capabilities", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("visibility", sa.Text(), server_default="public", nullable=False),
        sa.Column("owner_org_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.Text(), server_default="active", nullable=False),
        sa.Column("source", sa.Text(), server_default="generated", nullable=False),
        sa.Column("embedding", pgvector.sqlalchemy.vector.VECTOR(dim=1024), nullable=True),
        sa.Column(
            "meta",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.ForeignKeyConstraint(["owner_org_id"], ["org.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "owner_org_id", "name", "version", name="uq_role_template_owner_name_version"
        ),
        sa.CheckConstraint("visibility IN ('public','private','org')", name="visibility"),
        sa.CheckConstraint("status IN ('draft','active','archived')", name="status"),
        sa.CheckConstraint("source IN ('builtin','generated','user_saved')", name="source"),
    )
    op.create_index(
        "ix_role_template_embedding",
        "role_template",
        ["embedding"],
        unique=False,
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )


def downgrade() -> None:
    op.drop_index("ix_role_template_embedding", table_name="role_template")
    op.drop_table("role_template")
