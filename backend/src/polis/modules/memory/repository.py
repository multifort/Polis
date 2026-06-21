"""memory 数据访问层。集中 SQL（12 C 分层）。

组织级表，请求内靠 RLS、请求外(decay_job 等)靠 select_org_scoped 显式过滤（TD-015）。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import func, update
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
