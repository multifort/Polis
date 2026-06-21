"""MemoryCenter（design 05）：写入/检索管线。

M5：写入 = 抽取标准化 + 评分 + 去噪去重 + 出处入库（embedding 经 ModelGateway.embed，
M5 桩返 None、M6 接 LiteLLM）。检索（retrieve）见 M5-C。
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from polis.modules.memory import repository as repo
from polis.modules.memory.models import Memory
from polis.modules.model.gateway import ModelGateway

_MIN_CONTENT_LEN = 3


@dataclass
class Fact:
    """结果信封中的一条事实（design 05 §3/§7，出处贯穿）。"""

    content: str
    confidence: float = 0.5
    importance: float = 0.5
    provenance: dict[str, Any] | None = field(default=None)


# ── Extractor / Filter（确定性，无 LLM）──────────────────────────────────────────


def _normalize(content: str) -> str:
    """抽取标准化：折叠空白、去首尾。"""
    return re.sub(r"\s+", " ", content).strip()


def _is_noise(content: str) -> bool:
    """去噪：空 / 过短 / 纯标点。"""
    if len(content) < _MIN_CONTENT_LEN:
        return True
    return re.fullmatch(r"[\W_]+", content) is not None


def _score(fact: Fact) -> float:
    """评分 = importance × confidence，clamp 到 [0,1]。"""
    return max(0.0, min(1.0, fact.importance * fact.confidence))


# ── 写入管线 ──────────────────────────────────────────────────────────────────


async def write_facts(
    session: AsyncSession,
    gateway: ModelGateway,
    org_id: uuid.UUID,
    scope: str,
    namespace: str,
    facts: list[Fact],
    mem_type: str = "factual",
) -> list[Memory]:
    """写入管线：标准化→去噪→去重→评分→embedding→入库（出处随行）。返回实际写入的记忆。"""
    written: list[Memory] = []
    for fact in facts:
        content = _normalize(fact.content)
        if _is_noise(content):
            continue
        if await repo.find_by_content(session, org_id, scope, namespace, content) is not None:
            continue  # 去重（M5 内容精确；M6 换语义近邻）
        embedding = (await gateway.embed([content]))[0]
        mem = await repo.insert_memory(
            session,
            org_id=org_id,
            scope=scope,
            namespace=namespace,
            mem_type=mem_type,
            content=content,
            embedding=embedding,
            provenance=fact.provenance,
            importance=_score(fact),
            confidence=fact.confidence,
        )
        written.append(mem)
    return written


async def retrieve(
    session: AsyncSession, org_id: uuid.UUID, namespace: str, query: str, limit: int = 5
) -> str:
    """检索上下文切片（摘要）。M5-C 实现确定性检索（当前仍桩，返回空）。"""
    return ""
