"""MemoryCenter（design 05）：写入/检索管线。

M5：写入 = 抽取标准化 + 评分 + 去噪去重 + 出处入库（embedding 经 ModelGateway.embed，
M5 桩返 None、M6 接 LiteLLM）。检索（retrieve）见 M5-C。
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from polis.db.org_scoped import select_org_scoped
from polis.modules.memory import repository as repo
from polis.modules.memory.models import Memory, ResultEnvelope
from polis.modules.model.gateway import ChatMessage, ModelGateway, ResolvedModel

logger = logging.getLogger(__name__)

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
    promoted_from: uuid.UUID | None = None,
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
            promoted_from=promoted_from,
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
    query_embedding: list[float] | None = None,
    limit: int = 5,
) -> MemorySlice:
    """检索切片。query_embedding 可用→向量 RAG（M6-D）；否则确定性关键词（M5-C）。"""
    # 向量 RAG 路径（pgvector 余弦近邻，仅命中有 embedding 的记忆）
    if query_embedding is not None:
        hits = await repo.search_by_vector(
            session, org_id, scopes, query_embedding, limit, namespaces
        )
        if hits:
            await repo.touch_last_accessed(session, [m.id for m in hits])
            return MemorySlice(
                summaries=[m.content for m in hits],
                provenance=[m.provenance or {} for m in hits],
            )

    # 确定性关键词回退
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


# ── 自动晋升（task → org 蒸馏，V2-B3）─────────────────────────────────────────────

_ORG_NS = "company"  # org 级"公司知识"统一命名空间（供 B2 规划/编配接地检索）
_THETA_ORG_CONF = 0.7  # org 置信门（更高 + 必带出处，防把幻觉沉淀成"公司知识"，§5.2/§5.4）
_DISTILL_MAX = 5  # 单任务最多蒸馏出的事实数（控成本/防噪声）
_DISTILL_INPUT_CAP = 4000  # 喂给蒸馏的产出文本上限（字符）

_DISTILL_SYS = (
    "你从任务产出里抽取**对公司有长期复用价值的客观事实**（供应商画像/领域常识/历史结论等），"
    "用于公司知识库。只抽可复用、客观、可被后续任务当先验的事实；剔除过程性废话、一次性细节、主观语气。"
    f"最多 {_DISTILL_MAX} 条。"
    '严格输出 JSON 数组：[{"content":"事实","confidence":0~1}]，不要其他文字。'
)


def _parse_facts(raw: str) -> list[Fact]:
    """从 LLM 输出解析事实数组（容忍 ```json 围栏 / 噪声）。失败 → 空列表。"""
    s = raw.strip()
    if s.startswith("```"):
        s = s.split("```", 2)[1] if s.count("```") >= 2 else s.strip("`")
        if s.lstrip().lower().startswith("json"):
            s = s.lstrip()[4:]
    start, end = s.find("["), s.rfind("]")
    if start == -1 or end == -1 or end < start:
        return []
    try:
        items = json.loads(s[start : end + 1])
    except (ValueError, TypeError):
        return []
    out: list[Fact] = []
    for it in items if isinstance(items, list) else []:
        if isinstance(it, dict) and it.get("content"):
            try:
                conf = float(it.get("confidence", 0.5))
            except (TypeError, ValueError):
                conf = 0.5
            out.append(Fact(content=str(it["content"]), confidence=max(0.0, min(1.0, conf))))
    return out[:_DISTILL_MAX]


async def distill_facts(gateway: ModelGateway, model: ResolvedModel, text_blob: str) -> list[Fact]:
    """把任务产出蒸馏成若干条可复用客观事实（带 confidence）。LLM 失败/无产出 → 空列表。"""
    blob = (text_blob or "").strip()[:_DISTILL_INPUT_CAP]
    if not blob:
        return []
    try:
        rsp = await gateway.chat(
            model,
            [
                ChatMessage(role="system", content=_DISTILL_SYS),
                ChatMessage(role="user", content=f"任务产出：\n{blob}"),
            ],
        )
    except Exception:
        logger.warning("distill_facts LLM 调用失败，跳过本次蒸馏", exc_info=True)
        return []
    return _parse_facts(rsp.content or "")


async def promote_facts_from_task(
    session: AsyncSession,
    gateway: ModelGateway,
    model: ResolvedModel,
    org_id: uuid.UUID,
    task_id: uuid.UUID,
) -> dict[str, int]:
    """任务完成自动晋升（§5.2）：读本任务节点产出 → 蒸馏事实 → 高置信(≥θ)的 upsert 到 org 记忆。

    无人 curate（晋升是数据操作、风险低）；org 门更高 + 必带出处(promoted_from)，防幻觉沉淀。
    幂等：同 task 已晋升过（org 记忆有 promoted_from=task_id）则跳过。best-effort，不抛错。
    """
    # 幂等：本任务已晋升过 → 跳过
    seen = await session.scalar(
        select_org_scoped(Memory, org_id).where(
            Memory.scope == "org", Memory.promoted_from == task_id
        )
    )
    if seen is not None:
        return {"distilled": 0, "promoted": 0, "skipped": 1}

    envs = list(
        (
            await session.scalars(
                select_org_scoped(ResultEnvelope, org_id)
                .where(ResultEnvelope.task_id == task_id, ResultEnvelope.status == "done")
                .order_by(ResultEnvelope.created_at)
            )
        ).all()
    )
    blob = "\n\n".join((e.content or e.summary or "") for e in envs).strip()
    if not blob:
        return {"distilled": 0, "promoted": 0, "skipped": 0}

    facts = await distill_facts(gateway, model, blob)
    promoted = 0
    for fact in facts:
        if fact.confidence < _THETA_ORG_CONF:
            continue
        fact.provenance = {"promoted_from": str(task_id), "kind": "task_distill"}
        action, _ = await upsert_shared_fact(
            session, gateway, org_id, _ORG_NS, fact, promoted_from=task_id
        )
        if action in ("inserted", "overridden"):
            promoted += 1
    logger.info(
        "promote_facts_from_task org=%s task=%s 蒸馏 %d 条、晋升 %d 条",
        org_id,
        task_id,
        len(facts),
        promoted,
    )
    return {"distilled": len(facts), "promoted": promoted, "skipped": 0}
