"""planner 模块 ORM：能力词表/计划模板(全局) + 计划/任务运行(组织级)。

设计：docs/design/03、0b。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
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
from polis.db.mixins import OrgScopedMixin, TimestampMixin, UUIDPkMixin
from polis.modules.kernel.models import Plan as Plan
from polis.modules.kernel.models import TaskRun as TaskRun

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
    # R3 场景库树导航：大类 > 小类 > 具体场景
    domain: Mapped[str | None] = mapped_column(Text, nullable=True)
    subcategory: Mapped[str | None] = mapped_column(Text, nullable=True)
    acceptance_criteria: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 来源：builtin(平台内置) / user_saved(用户存为模板)
    source: Mapped[str] = mapped_column(Text, server_default="builtin")

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


class Task(UUIDPkMixin, OrgScopedMixin, Base):
    """可复用工作项（V2-P1）：name/goal + 场景引用 + 输入；一个 task 多次运行(task_run)。"""

    __tablename__ = "task"

    name: Mapped[str] = mapped_column(Text)
    scenario_ref: Mapped[str | None] = mapped_column(Text)  # plan_template 名（nullable）
    goal: Mapped[str] = mapped_column(Text)
    input_schema: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    inputs: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id"))
    priority: Mapped[int] = mapped_column(Integer, server_default="0")
    status: Mapped[str] = mapped_column(Text, server_default="active")
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))


class SceneCategory(UUIDPkMixin, TimestampMixin, Base):
    """场景库分类（R3/P5）：org 级可维护的 大类 > 子类 树。

    平台内置分类 org_id=NULL（所有公司可见），org 可追加自己的私有分类。
    """

    __tablename__ = "scene_category"

    org_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("org.id"), nullable=True)
    domain: Mapped[str] = mapped_column(Text)
    subcategory: Mapped[str | None] = mapped_column(Text, nullable=True)
    display_order: Mapped[int] = mapped_column(server_default="0")

    __table_args__ = (
        UniqueConstraint(
            "org_id", "domain", "subcategory", name="uq_scene_category_org_domain_sub"
        ),
    )
