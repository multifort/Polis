"""planner 模块 ORM：能力词表/计划模板(全局) + 计划/任务运行(组织级)。

设计：docs/design/03、0b。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Index, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from polis.db.base import Base
from polis.db.mixins import OrgScopedMixin, TimestampMixin, UUIDPkMixin

# ---- 全局共享 ----


class Capability(Base):
    """受控能力词表，主键即 key（如 'procurement.supplier_analysis'）。"""

    __tablename__ = "capability"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    domain: Mapped[str | None] = mapped_column(Text)
    name: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1024))

    __table_args__ = (
        Index(
            "ix_capability_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )


class PlanTemplate(UUIDPkMixin, Base):
    __tablename__ = "plan_template"

    name: Mapped[str] = mapped_column(Text)
    version: Mapped[str] = mapped_column(Text)
    dag_skeleton: Mapped[dict[str, Any]] = mapped_column(JSONB)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1024))
    # V2-R1 可见性：public=全 org 可见（默认/平台内置）；private=仅属主 org
    visibility: Mapped[str] = mapped_column(Text, server_default="public")
    owner_org_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("org.id"))

    __table_args__ = (
        UniqueConstraint("name", "version", name="uq_plan_template_name_version"),
        Index(
            "ix_plan_template_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )


# ---- 组织级 ----


class Plan(UUIDPkMixin, OrgScopedMixin, Base):
    __tablename__ = "plan"

    goal: Mapped[str | None] = mapped_column(Text)
    dag: Mapped[dict[str, Any]] = mapped_column(JSONB)
    version: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default="draft")
    estimated_cost_cents: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))

    __table_args__ = (
        CheckConstraint("status IN ('draft','approved','running','done','failed')", name="status"),
    )


class TaskRun(UUIDPkMixin, OrgScopedMixin, TimestampMixin, Base):
    """任务运行锚点：承载 task_id，关联 plan 与 Temporal 工作流（0b §2 修订 C）。"""

    __tablename__ = "task_run"

    plan_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("plan.id"))
    temporal_workflow_id: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default="pending")
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]

    __table_args__ = (
        CheckConstraint("status IN ('pending','running','paused','done','failed')", name="status"),
    )
