"""memory 模块 ORM：统一记忆 + 结果信封 + 产物描述符（均组织级，0b 补 org_id）。

设计：docs/design/05、0b。hnsw 向量索引在迁移中手工补（autogenerate 覆盖不到）。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    CheckConstraint,
    Float,
    Index,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from polis.db.base import Base
from polis.db.mixins import OrgScopedMixin, UUIDPkMixin
from polis.modules.kernel.models import ArtifactDescriptor as ArtifactDescriptor
from polis.modules.kernel.models import ResultEnvelope as ResultEnvelope


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
    # V2-B3 晋升溯源：promoted_from=晋升来源(如 task_run.id)；last_promoted_at=最近晋升时间
    promoted_from: Mapped[uuid.UUID | None]
    last_promoted_at: Mapped[datetime | None]

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
