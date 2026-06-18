"""通用 ORM mixin：UUID 主键 / 时间戳 / org 作用域（落实 12 C + 0b 约定）。"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, func, text
from sqlalchemy.orm import Mapped, mapped_column


class UUIDPkMixin:
    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=text("gen_random_uuid()")
    )


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class OrgScopedMixin:
    """组织级表统一带 org_id（受 RLS）。org 表自身不用此 mixin（其 id 即 org_id）。"""

    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("org.id", ondelete="CASCADE"), index=True)
