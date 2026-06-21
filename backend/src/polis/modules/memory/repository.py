"""memory 数据访问层。集中 SQL（12 C 分层）。

组织级表，请求内靠 RLS、请求外(decay_job 等)靠 select_org_scoped 显式过滤（TD-015）。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, cast

from sqlalchemy import CursorResult, func, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from polis.db.org_scoped import select_org_scoped
from polis.modules.memory.models import Memory


async def insert_memory(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    scope: str,
    namespace: str,
    mem_type: str,
    content: str,
    embedding: list[float] | None = None,
    provenance: dict[str, Any] | None = None,
    importance: float = 0.5,
    confidence: float = 0.5,
    expires_at: datetime | None = None,
) -> Memory:
    mem = Memory(
        org_id=org_id,
        scope=scope,
        namespace=namespace,
        type=mem_type,
        content=content,
        embedding=embedding,
        provenance=provenance,
        importance=importance,
        confidence=confidence,
        expires_at=expires_at,
    )
    session.add(mem)
    await session.flush()
    return mem


async def list_by_scope(
    session: AsyncSession,
    org_id: uuid.UUID,
    scopes: list[str],
    namespaces: list[str] | None = None,
) -> list[Memory]:
    """按作用域(scope)+可选 namespace 取记忆（org 显式过滤）。"""
    q = select_org_scoped(Memory, org_id).where(Memory.scope.in_(scopes))
    if namespaces:
        q = q.where(Memory.namespace.in_(namespaces))
    return list((await session.scalars(q)).all())


async def list_for_org(session: AsyncSession, org_id: uuid.UUID, limit: int = 100) -> list[Memory]:
    """治理浏览：列该 org 记忆（按创建时间倒序）。"""
    q = select_org_scoped(Memory, org_id).order_by(Memory.created_at.desc()).limit(limit)
    return list((await session.scalars(q)).all())


async def get_by_id(
    session: AsyncSession, org_id: uuid.UUID, memory_id: uuid.UUID
) -> Memory | None:
    q = select_org_scoped(Memory, org_id).where(Memory.id == memory_id).limit(1)
    mem: Memory | None = await session.scalar(q)
    return mem


async def delete_memory(session: AsyncSession, mem: Memory) -> None:
    await session.delete(mem)
    await session.flush()


async def find_by_content(
    session: AsyncSession, org_id: uuid.UUID, scope: str, namespace: str, content: str
) -> Memory | None:
    """按内容精确匹配查重（M5 去重桩；M6 换语义近邻 find_similar）。"""
    q = (
        select_org_scoped(Memory, org_id)
        .where(Memory.scope == scope, Memory.namespace == namespace, Memory.content == content)
        .limit(1)
    )
    mem: Memory | None = await session.scalar(q)
    return mem


async def touch_last_accessed(session: AsyncSession, ids: list[uuid.UUID]) -> None:
    if not ids:
        return
    await session.execute(update(Memory).where(Memory.id.in_(ids)).values(last_accessed=func.now()))
    await session.flush()


async def decay_and_cleanup(session: AsyncSession) -> dict[str, int]:
    """衰减/遗忘（design 05 §5）：importance 按 age 指数衰减 + 删低价值 event + 删过期。

    全表运维任务（跨 org）。返回各类删除行数。
    """
    await session.execute(
        text(
            "UPDATE memory SET importance = importance * "
            "exp(-decay_rate * (EXTRACT(EPOCH FROM (now() - created_at)) / 86400.0))"
        )
    )
    low = cast(
        "CursorResult[Any]",
        await session.execute(
            text("DELETE FROM memory WHERE importance < 0.05 AND type = 'event'")
        ),
    )
    expired = cast(
        "CursorResult[Any]",
        await session.execute(
            text("DELETE FROM memory WHERE expires_at IS NOT NULL AND expires_at < now()")
        ),
    )
    await session.flush()
    return {"low_value_deleted": low.rowcount, "expired_deleted": expired.rowcount}
