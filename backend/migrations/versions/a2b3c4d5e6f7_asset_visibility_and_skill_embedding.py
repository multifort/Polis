"""V2-R1 检索底座：plan_template/skill 加 visibility + owner_org_id + skill embedding

Revision ID: a2b3c4d5e6f7
Revises: 9a1b2c3d4e5f
Create Date: 2026-06-22 22:00:00.000000

向后兼容：visibility 默认 'public'（旧行=公共，全 org 可见，不改既有可见性）；
plan_template 加 owner_org_id(nullable，私有模板用)；skill 加 embedding(nullable)+hnsw（供语义检索）。
"""

from __future__ import annotations

from collections.abc import Sequence

import pgvector.sqlalchemy
import sqlalchemy as sa
from alembic import op

revision: str = "a2b3c4d5e6f7"
down_revision: str | None = "9a1b2c3d4e5f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 场景模板（plan_template）：可见性 + 私有归属（embedding/hnsw 已在 m1 基线）
    op.add_column(
        "plan_template",
        sa.Column("visibility", sa.Text(), nullable=False, server_default="public"),
    )
    op.add_column(
        "plan_template",
        sa.Column("owner_org_id", sa.Uuid(), sa.ForeignKey("org.id"), nullable=True),
    )

    # Skill：可见性 + embedding(语义检索) + hnsw
    op.add_column(
        "skill",
        sa.Column("visibility", sa.Text(), nullable=False, server_default="public"),
    )
    op.add_column(
        "skill",
        sa.Column("embedding", pgvector.sqlalchemy.vector.VECTOR(dim=1024), nullable=True),
    )
    op.create_index(
        "ix_skill_embedding",
        "skill",
        ["embedding"],
        unique=False,
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )


def downgrade() -> None:
    op.drop_index("ix_skill_embedding", table_name="skill")
    op.drop_column("skill", "embedding")
    op.drop_column("skill", "visibility")
    op.drop_column("plan_template", "owner_org_id")
    op.drop_column("plan_template", "visibility")
