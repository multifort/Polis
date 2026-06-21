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


@dataclass
class MemorySlice:
    """检索结果切片：注入摘要 + 出处（design 05 §4，注入摘要非全量）。"""

    summaries: list[str] = field(default_factory=list)
    provenance: list[dict[str, Any]] = field(default_factory=list)

    def to_text(self) -> str:
        return "\n".join(f"- {s}" for s in self.summaries)


def _terms(text: str) -> set[str]:
    """英文词(小写) + 中文单字，作为确定性相关性的 token 集（M6 换 embedding 语义）。"""
    en = set(re.findall(r"[a-z0-9]+", text.lower()))
    zh = set(re.findall(r"[一-鿿]", text))
    return en | zh


async def upsert_shared_fact(
    session: AsyncSession,
    gateway: ModelGateway,
    org_id: uuid.UUID,
    namespace: str,
    fact: Fact,
) -> tuple[str, Memory]:
    """共享(org 作用域)记忆并发裁决（design 05 §6）。

    近邻不存在→insert；新事实置信更高→覆盖；否则→标记 conflict（不静默硬合并，交人裁决）。
    M5 用内容精确匹配做近邻（桩）；M6 换语义近邻 find_similar。
    返回 (action, memory)，action ∈ inserted|overridden|conflict。
    """
    content = _normalize(fact.content)
    old = await repo.find_by_content(session, org_id, "org", namespace, content)
    if old is None:
        embedding = (await gateway.embed([content]))[0]
        mem = await repo.insert_memory(
            session,
            org_id=org_id,
            scope="org",
            namespace=namespace,
            mem_type="factual",
            content=content,
            embedding=embedding,
            provenance=fact.provenance,
            importance=_score(fact),
            confidence=fact.confidence,
        )
        return ("inserted", mem)

    if fact.confidence > old.confidence:
        old.content = content
        old.confidence = fact.confidence
        old.importance = _score(fact)
        old.provenance = fact.provenance
        await session.flush()
        return ("overridden", old)

    # 冲突：标记而非静默合并
    old.provenance = {
        **(old.provenance or {}),
        "conflict": True,
        "competing_content": content,
        "competing_confidence": fact.confidence,
    }
    await session.flush()
    return ("conflict", old)


async def retrieve(
    session: AsyncSession,
    org_id: uuid.UUID,
    *,
    scopes: list[str],
    namespaces: list[str] | None = None,
    query: str,
    limit: int = 5,
) -> MemorySlice:
    """确定性检索（M5-C，待 M6 切向量 RAG）。

    作用域权限过滤 → 关键词相关性 + importance + recency 排序 → 返回 top-K 摘要 + 出处 + touch。
    """
    rows = await repo.list_by_scope(session, org_id, scopes, namespaces)
    if not rows:
        return MemorySlice()

    q_terms = _terms(query)

    def _relevance(mem: Memory) -> int:
        return len(q_terms & _terms(mem.content))

    # 排序键：相关性 > importance > 最近访问（recency）
    rows.sort(key=lambda m: (_relevance(m), m.importance, m.last_accessed), reverse=True)
    top = rows[:limit]
    await repo.touch_last_accessed(session, [m.id for m in top])
    return MemorySlice(
        summaries=[m.content for m in top],
        provenance=[m.provenance or {} for m in top],
    )
