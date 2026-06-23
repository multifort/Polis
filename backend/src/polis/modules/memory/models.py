"""memory 模块 ORM：统一记忆 + 结果信封 + 产物描述符（均组织级，0b 补 org_id）。

设计：docs/design/05、0b。hnsw 向量索引在迁移中手工补（autogenerate 覆盖不到）。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    Integer,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from polis.db.base import Base
from polis.db.mixins import OrgScopedMixin, UUIDPkMixin


class Memory(UUIDPkMixin, OrgScopedMixin, Base):
    __tablename__ = "memory"

    scope: Mapped[str] = mapped_column(Text)
    namespace: Mapped[str] = mapped_column(Text)
    type: Mapped[str] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1024))
    provenance: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    importance: Mapped[float] = mapped_column(Float, server_default="0.5")
    confidence: Mapped[float] = mapped_column(Float, server_default="0.5")
    decay_rate: Mapped[float] = mapped_column(Float, server_default="0.01")
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    last_accessed: Mapped[datetime] = mapped_column(server_default=text("now()"))
    expires_at: Mapped[datetime | None]

    __table_args__ = (
        CheckConstraint("scope IN ('session','task','role','org')", name="scope"),
        CheckConstraint("type IN ('factual','procedural','preference','event')", name="type"),
        Index("ix_memory_org_scope_ns", "org_id", "scope", "namespace"),
        Index(
            "ix_memory_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )


class ResultEnvelope(UUIDPkMixin, OrgScopedMixin, Base):
    __tablename__ = "result_envelope"

    task_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("task_run.id"))
    node_id: Mapped[str | None] = mapped_column(Text)
    agent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agent.id"))
    status: Mapped[str | None] = mapped_column(Text)
    artifacts: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    facts: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    summary: Mapped[str | None] = mapped_column(Text)
    content: Mapped[str | None] = mapped_column(Text)  # 全文（V2-B1 黑板，懒加载）
    tokens: Mapped[int | None] = mapped_column(Integer)  # 产出 token 估算（预算）
    needs_human: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))


class ArtifactDescriptor(UUIDPkMixin, OrgScopedMixin, Base):
    __tablename__ = "artifact_descriptor"

    task_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("task_run.id"))
    node_id: Mapped[str | None] = mapped_column(Text)
    modality: Mapped[str | None] = mapped_column(Text)
    uri: Mapped[str | None] = mapped_column(Text)
    mime: Mapped[str | None] = mapped_column(Text)
    caption: Mapped[str | None] = mapped_column(Text)
    provenance: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    meta: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
