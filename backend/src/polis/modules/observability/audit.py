"""审计写入（TD-011）：关键写操作落 audit_log，操作留痕（07§1.1）。"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession

from polis.modules.observability.models import AuditLog


async def write_audit(
    session: AsyncSession,
    *,
    action: str,
    actor: str | None = None,
    org_id: uuid.UUID | None = None,
    target: str | None = None,
    detail: dict[str, Any] | None = None,
) -> None:
    await session.execute(
        insert(AuditLog).values(
            org_id=org_id, actor=actor, action=action, target=target, detail=detail
        )
    )
