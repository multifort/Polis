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
    sk = t.dag_skeleton or {}
    return f"{t.name} {sk.get('workflow_name', '')} {sk.get('acceptance_criteria', '')}"


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
