"""MemoryCenter（design 05）。

M4 桩（ADR-0007）：retrieve 返回空切片（无历史检索）、write_fact 直写 memory（无评分/去噪/去重）。
M5 换真实管线：RAG 检索 + rerank + 作用域权限过滤；写入抽取 + 评分 + 过滤 + 出处入库。
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from polis.modules.memory.models import Memory


async def retrieve(
    session: AsyncSession, org_id: uuid.UUID, namespace: str, query: str, limit: int = 5
) -> str:
    """检索上下文切片（摘要）。M4 桩：返回空串（M5 接 RAG）。"""
    return ""


async def write_fact(
    session: AsyncSession,
    org_id: uuid.UUID,
    namespace: str,
    content: str,
    provenance: dict[str, Any] | None = None,
) -> Memory:
    """写回一条事实记忆。M4 桩：直写（无评分/去噪/去重）。M5 换 write 管线。"""
    mem = Memory(
        org_id=org_id,
        scope="task",
        namespace=namespace,
        type="factual",
        content=content,
        provenance=provenance,
    )
    session.add(mem)
    await session.flush()
    return mem
