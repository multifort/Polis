"""embedding 回填 CLI（V2-R1）：给 capability/plan_template/skill 的空 embedding 回填向量。

接 LiteLLM/TEI（需 text-embeddings 服务在跑，见续接指南 §3）。幂等：只填 embedding IS NULL 的行。
为 A1 语义检索（模板/技能/能力）提供底料。
运行：`uv run python -m polis.modules.model.embed_backfill`（或 `make embed-backfill`）。
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from polis.db.session import dispose_engine, get_sessionmaker, init_engine
from polis.modules.model.gateway import ModelGateway
from polis.modules.model.litellm_gateway import LiteLLMGateway
from polis.modules.planner.models import Capability, PlanTemplate
from polis.modules.runtime.models import Skill


async def _embed_rows(gateway: ModelGateway, rows: list[Any], text_of: Callable[[Any], str]) -> int:
    n = 0
    for r in rows:
        txt = text_of(r).strip()
        if not txt:
            continue
        vec = (await gateway.embed([txt]))[0]
        if vec is not None:
            r.embedding = vec
            n += 1
    return n


def _tpl_text(t: PlanTemplate) -> str:
    """模板的语义检索源文本：聚合中文「验收标准 + 各节点意图/产出」。

    不用 name/workflow_name（英文标识符，对 bge-zh 是噪声、拉低与中文 goal 的相似度——实测
    同域目标仅 ~0.5–0.7）。改用节点 input_hint/expected_output 的中文意图后，同域升到 ~0.57–0.69、
    跨域降到 ~0.36–0.41，分离清晰（详见 A1 检索校准）。
    """
    sk = t.dag_skeleton or {}
    parts: list[str] = [str(sk.get("acceptance_criteria") or "")]
    for n in sk.get("nodes", []):
        parts.append(str(n.get("input_hint") or ""))
        parts.append(str(n.get("expected_output") or ""))
    text = " ".join(p for p in parts if p).strip()
    return text or t.name  # 兜底：骨架无中文文本时退回 name


async def backfill() -> dict[str, int]:
    """回填三类全局目录的空 embedding，返回各表回填行数。"""
    init_engine()
    gateway: ModelGateway = LiteLLMGateway()
    counts: dict[str, int] = {}
    try:
        async with get_sessionmaker()() as session:
            await _backfill_session(session, gateway, counts)
            await session.commit()
    finally:
        await dispose_engine()
    return counts


async def _backfill_session(
    session: AsyncSession, gateway: ModelGateway, counts: dict[str, int]
) -> None:
    cap_q = select(Capability).where(Capability.embedding.is_(None))
    caps = list((await session.scalars(cap_q)).all())
    counts["capability"] = await _embed_rows(
        gateway, caps, lambda c: f"{c.name or ''} {c.description or ''}"
    )
    tpls = list(
        (await session.scalars(select(PlanTemplate).where(PlanTemplate.embedding.is_(None)))).all()
    )
    counts["plan_template"] = await _embed_rows(gateway, tpls, _tpl_text)
    sks = list((await session.scalars(select(Skill).where(Skill.embedding.is_(None)))).all())
    counts["skill"] = await _embed_rows(gateway, sks, lambda s: f"{s.name} {s.capability or ''}")


def main() -> None:
    counts = asyncio.run(backfill())
    print(f"embedding 回填完成：{counts}")


if __name__ == "__main__":
    main()
