"""observability 模块 ORM：Run Manifest / 审批 / Trace 引用 / 审计日志。

设计：docs/design/06、07、0b。trace_ref 为 0b 补的 DDL；audit_log 的 org_id 可空。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from polis.db.base import Base
from polis.db.mixins import OrgScopedMixin, UUIDPkMixin


class RunManifest(OrgScopedMixin, Base):
    """任务可复现快照，主键即 task_id。"""

    __tablename__ = "run_manifest"

    task_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("task_run.id", ondelete="CASCADE"), primary_key=True
    )
    started_at: Mapped[datetime | None]
    agents_used: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    skills_used: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    models_used: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    plan_version: Mapped[str | None] = mapped_column(Text)
    plan_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class Approval(UUIDPkMixin, OrgScopedMixin, Base):
    __tablename__ = "approval"

    kind: Mapped[str] = mapped_column(Text)
    ref_id: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(Text, server_default="pending")
    assignee: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id"))
    decided_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id"))
    decided_at: Mapped[datetime | None]

    __table_args__ = (
        CheckConstraint(
            "kind IN ('plan','dangerous_action','provision_review','skill_review','rework')",
            name="kind",
        ),
        CheckConstraint("status IN ('pending','approved','rejected')", name="status"),
    )


class TraceRef(UUIDPkMixin, OrgScopedMixin, Base):
    __tablename__ = "trace_ref"

    task_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("task_run.id"))
    langfuse_trace_id: Mapped[str | None] = mapped_column(Text)
    plan_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("plan.id"))
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    org_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("org.id", ondelete="SET NULL"), index=True
    )
    actor: Mapped[str | None] = mapped_column(Text)
    action: Mapped[str | None] = mapped_column(Text)
    target: Mapped[str | None] = mapped_column(Text)
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    at: Mapped[datetime] = mapped_column(server_default=text("now()"))
