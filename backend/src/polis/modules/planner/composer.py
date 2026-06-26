"""A3 编配生成：节点无现成 Agent → 拼已审 Skill 成 Agent（自动，无人审）。

设计：docs/design/v2/01 §5.2–5.4 / §14.5（ADR-0010 角色驱动主干 + 任务驱动弹性）。
洞察：Skill 是唯一的「新代码」资产；Agent 只是「已审 Skill 之上的配置拼装」。因此拼装
已有 Skill 成 Agent **不产生新代码 → 可自动生成、不卡人审**；只有「某能力连 Skill 都没有」
才撞人审墙（生成 Skill 草稿走审核——A3 暂不做，缺 Skill 即返 None＝该能力暂不可办）。
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from polis.db.org_scoped import select_org_scoped, visible_clause
from polis.modules.org.models import Agent, AgentCapability, AgentVersion
from polis.modules.org.schemas import AgentConfig
from polis.modules.planner.router import select_agent
from polis.modules.planner.schemas import PlanDag
from polis.modules.runtime.models import Skill

logger = logging.getLogger(__name__)

_COMPOSED_PREFIX = "弹性组队"  # 临时组队 Agent 名前缀（任务驱动弹性）
# Skill 候选优先级：official > verified > community > private（同能力多候选取信任最高）
_TRUST_ORDER = {"official": 0, "verified": 1, "community": 2, "private": 3}


def _compose_name(caps: list[str]) -> str:
    """从能力集派生确定性名字（org 内唯一约束 → 同能力集幂等复用，不重复造）。"""
    return f"{_COMPOSED_PREFIX}·" + "+".join(sorted(caps))


def _compose_prompt(caps: list[str]) -> str:
    return (
        "你是按任务临时组建的智能体，负责以下能力：" + "、".join(sorted(caps)) + "。"
        "请基于上游节点的输入，调用你被赋予的技能完成本环节工作，"
        "产出结构化、可执行、可验证的结果，并说明依据。"
    )


async def _retrieve_skill(session: AsyncSession, org_id: uuid.UUID, cap: str) -> Skill | None:
    """为某能力找一个可用 Skill：published + 对本 org 可见，按信任度优先。无 → None。"""
    rows = (
        await session.scalars(
            select(Skill).where(
                Skill.capability == cap,
                Skill.status == "published",
                visible_clause(Skill, org_id),
            )
        )
    ).all()
    if not rows:
        return None
    return sorted(rows, key=lambda s: _TRUST_ORDER.get(s.trust, 9))[0]


async def compose_agent(session: AsyncSession, org_id: uuid.UUID, caps: list[str]) -> Agent | None:
    """拼装一个覆盖 caps 的 Agent：每能力取一个 published Skill，全有则建 Agent（自动 active）。

    幂等：同能力集已组过的 active 组队 Agent 直接复用。缺任一 Skill → None（A3 不生成草稿）。
    """
    caps = list(dict.fromkeys(caps))  # 去重保序
    if not caps:
        return None

    name = _compose_name(caps)
    # 显式 org 过滤（请求外不依赖 RLS，TD-015）：避免跨 org 同名组队 Agent 误复用
    existing = await session.scalar(
        select_org_scoped(Agent, org_id).where(Agent.name == name, Agent.status == "active")
    )
    if existing is not None:
        return existing

    chosen: dict[str, Skill] = {}
    for cap in caps:
        sk = await _retrieve_skill(session, org_id, cap)
        if sk is None:
            logger.info("compose_agent 缺 Skill 提供能力 %s → 放弃拼装（需补 Skill）", cap)
            return None
        chosen[cap] = sk

    cfg = AgentConfig(
        prompt=_compose_prompt(caps),
        capabilities=caps,
        skills=[s.name for s in chosen.values()],
        executor="lite-agent",
        provenance={"composed_from": {c: s.name for c, s in chosen.items()}},
    )
    agent = Agent(
        org_id=org_id,
        role_id=None,  # 临时组队不挂常设角色（高频复用时再晋升，§5.1）
        name=name,
        source="generated",
        status="active",  # 拼装＝配置类、不产生新代码 → 自动激活、不卡人审（§5.3）
        current_version="v1",
    )
    session.add(agent)
    await session.flush()
    session.add(
        AgentVersion(
            org_id=org_id,
            agent_id=agent.id,
            version="v1",
            config=cfg.model_dump(),
            status="published",
        )
    )
    for cap in caps:
        session.add(AgentCapability(org_id=org_id, agent_id=agent.id, capability=cap))
    await session.flush()
    logger.info("compose_agent 拼装 Agent %s 覆盖能力 %s（来自 %s）", name, caps, cfg.skills)
    return agent


async def route_or_compose(
    session: AsyncSession, org_id: uuid.UUID, dag: PlanDag
) -> dict[str, str | None]:
    """逐 agent 节点路由：① 检索现有 Agent；无→② 拼 Skill 成 Agent（§5.2）。返回 node→Agent 名。"""
    routing: dict[str, str | None] = {}
    for node in dag.nodes:
        if node.type != "agent" or not node.required_capabilities:
            continue
        agent = await select_agent(session, node.required_capabilities)
        if agent is None:
            agent = await compose_agent(session, org_id, node.required_capabilities)
        routing[node.id] = agent.name if agent is not None else None
    return routing
