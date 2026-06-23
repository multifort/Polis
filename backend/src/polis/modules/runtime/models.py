"""runtime 模块 ORM：技能注册/版本(全局，私有可带 owner_org_id) + 调用日志(组织级)。

设计：docs/design/04、0b。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from polis.db.base import Base
from polis.db.mixins import OrgScopedMixin, UUIDPkMixin

# ---- 全局共享（私有技能带 owner_org_id）----


class Skill(UUIDPkMixin, Base):
    __tablename__ = "skill"

    name: Mapped[str] = mapped_column(Text, unique=True)
    kind: Mapped[str] = mapped_column(Text)
    trust: Mapped[str] = mapped_column(Text, server_default="private")
    status: Mapped[str] = mapped_column(Text, server_default="draft")
    capability: Mapped[str | None] = mapped_column(Text)
    owner: Mapped[str | None] = mapped_column(Text)
    owner_org_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("org.id"))
    # V2-R1：可见性（public=全 org 可见/默认）+ embedding（语义检索）
    visibility: Mapped[str] = mapped_column(Text, server_default="public")
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1024))

    __table_args__ = (
        CheckConstraint("kind IN ('manual','tool')", name="kind"),
        CheckConstraint("trust IN ('official','verified','community','private')", name="trust"),
        CheckConstraint("status IN ('draft','published','deprecated')", name="status"),
        Index(
            "ix_skill_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )


class SkillVersion(UUIDPkMixin, Base):
    __tablename__ = "skill_version"

    skill_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("skill.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[str] = mapped_column(Text)
    content: Mapped[str | None] = mapped_column(Text)
    mcp_server: Mapped[str | None] = mapped_column(Text)
    tool: Mapped[str | None] = mapped_column(Text)
    io_schema: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    permissions: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    __table_args__ = (UniqueConstraint("skill_id", "version", name="skill_id_version"),)


# ---- 组织级 ----


class SkillInvocation(UUIDPkMixin, OrgScopedMixin, Base):
    __tablename__ = "skill_invocation"

    agent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agent.id"))
    skill_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("skill.id"))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    cost_cents: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
