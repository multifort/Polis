"""observability 模块 ORM：Run Manifest / 审批 / Trace 引用 / 审计日志。

设计：docs/design/06、07、0b。trace_ref 为 0b 补的 DDL；audit_log 的 org_id 可空。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    ForeignKey,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from polis.db.base import Base
from polis.db.mixins import OrgScopedMixin, UUIDPkMixin
from polis.modules.kernel.models import Approval as Approval
from polis.modules.kernel.models import RunManifest as RunManifest


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
