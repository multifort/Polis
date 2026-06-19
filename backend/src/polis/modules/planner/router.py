"""确定性能力路由（ADR-0006，无 LLM）：按冷启动打分挑选当前公司里能力匹配的 Agent。

M6 再接 embedding/历史表现。这里只做能力覆盖率 + 占位的成本/时延项。
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from polis.modules.org.models import Agent, AgentCapability


async def select_agent(session: AsyncSession, required: list[str]) -> Agent | None:
    """在当前公司（RLS 限定）里挑选最适合承接 required 能力的 active Agent。

    打分（冷启动）：0.6*能力覆盖率 + 0.25(成本占位最优) + 0.15(时延占位最优)。
    覆盖率 = 命中的 required 能力数 / required 总数。无匹配返回 None。
    """
    if not required:
        return None

    required_set = set(required)
    rows = await session.execute(
        select(Agent, AgentCapability.capability)
        .join(AgentCapability, AgentCapability.agent_id == Agent.id)
        .where(Agent.status == "active", AgentCapability.capability.in_(required_set))
    )

    # 聚合到 python：每个候选 Agent 命中了哪些 required 能力
    matched: dict[Agent, set[str]] = {}
    for agent, capability in rows.all():
        matched.setdefault(agent, set()).add(capability)

    if not matched:
        return None

    def score(caps: set[str]) -> float:
        coverage = len(caps) / len(required_set)
        return 0.6 * coverage + 0.25 + 0.15

    best = max(matched.items(), key=lambda kv: score(kv[1]))
    return best[0]
