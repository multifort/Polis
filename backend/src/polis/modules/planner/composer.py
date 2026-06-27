"""A3 编配生成 + A4 自动背书：节点无现成 Agent → 拼已审 Skill 成 Agent，eval 背书后启用。

设计：docs/design/v2/01 §5.2–5.4 / §6 / §13.2 / §14.5（ADR-0010 角色驱动主干 + 任务驱动弹性）。
洞察：Skill 是唯一的「新代码」资产；Agent 只是「已审 Skill 之上的配置拼装」。因此拼装
已有 Skill 成 Agent **不产生新代码 → 可自动生成 + 自动 eval 背书、不卡人审**；只有「某能力连
Skill 都没有」才撞人审墙（生成 Skill 草稿走审核——A3 暂不做，缺 Skill 即返 None）。
A4 自动背书（advisory）：拼装后用 Evaluator 给一份「胜任度」judge 快照写进 config.eval（观测 +
采纳率基线）。注意——此 judge 只见技能名/岗位说明（非「试产出」），是弱信号，故**不硬门控**激活；
权威背书仍是 S1 执行期质量门（对真实节点产出 judge→needs_rework）。基于「试产出/执行 eval」的
硬降级留作后续（TD-033）。
"""

from __future__ import annotations

import datetime as dt
import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from polis.config import get_settings
from polis.db.org_scoped import select_org_scoped, visible_clause
from polis.modules.model.gateway import ModelGateway, resolve_model
from polis.modules.observability import evaluator
from polis.modules.org.models import Agent, AgentCapability, AgentVersion
from polis.modules.org.schemas import AgentConfig
from polis.modules.planner.router import select_agent
from polis.modules.planner.schemas import PlanDag
from polis.modules.planner.skillgen import generate_skill_draft
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


_EVAL_TAU = 0.6  # 拼装 Agent 自动背书 judge 阈值（design §14.6 阈值表初值）


async def _endorse(
    gateway: ModelGateway, caps: list[str], cfg: AgentConfig, session: AsyncSession
) -> dict[str, object]:
    """A4 自动背书：judge 拼装出的 Agent 是否胜任 caps。返回 eval 快照（judge/passed/at）。

    配置类拼装不产生新代码 → 自动 eval 背书、不卡人审（§13.2）。这里用一次轻量 judge（非全 Agent
    试跑）：把岗位说明+技能+声明能力作为「待评对象」，让模型判其是否足以胜任。失败由调用方降级。
    """
    model = await resolve_model(session, get_settings().default_chat_model)
    described = (
        f"岗位说明：{cfg.prompt}\n绑定技能：{'、'.join(cfg.skills)}\n声明能力：{'、'.join(caps)}"
    )
    criteria = (
        f"该智能体的技能与岗位说明是否足以胜任能力【{'、'.join(caps)}】并产出合格、可执行的结果"
    )
    res = await evaluator.score(gateway, model, described, acceptance_criteria=criteria)
    return {
        "judge": res.judge_score,
        "passed": res.judge_score >= _EVAL_TAU,
        "at": dt.datetime.now(dt.UTC).isoformat(),
        "kind": "compose_fitness",
    }


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


async def compose_agent(
    session: AsyncSession,
    org_id: uuid.UUID,
    caps: list[str],
    *,
    gateway: ModelGateway | None = None,
) -> Agent | None:
    """拼装一个覆盖 caps 的 Agent：每能力取一个 published Skill，全有则建 active Agent。

    A4：给了 gateway → 附一份 advisory 胜任度 eval 快照进 config.eval（不硬门控激活，见模块注释）。
    无 gateway（TEI 不可达/测试）→ 跳过 eval。幂等：同能力集已建过的 active Agent 直接复用。
    缺任一 Skill → None（A3 不生成草稿）。
    """
    caps = list(dict.fromkeys(caps))  # 去重保序
    if not caps:
        return None

    name = _compose_name(caps)
    # 显式 org 过滤（请求外不依赖 RLS，TD-015）
    existing = await session.scalar(
        select_org_scoped(Agent, org_id).where(Agent.name == name, Agent.status == "active")
    )
    if existing is not None:
        return existing

    chosen: dict[str, Skill] = {}
    missing: list[str] = []
    for cap in caps:
        sk = await _retrieve_skill(session, org_id, cap)
        if sk is None:
            missing.append(cap)
        else:
            chosen[cap] = sk
    if missing:
        # 撞人审墙（TD-032）：为缺 Skill 的能力生成草稿 + skill_review 审批（不自动发布）。
        # 本节点暂不可用（返 None），待人审通过发布后下次拼装。无 gateway 则仅记日志（不阻断）。
        if gateway is not None:
            for cap in missing:
                await generate_skill_draft(session, org_id, cap, gateway)
        logger.info("compose_agent 缺 Skill 能力 %s → 已生成草稿待人审，暂不覆盖", missing)
        return None

    cfg = AgentConfig(
        prompt=_compose_prompt(caps),
        capabilities=caps,
        skills=[s.name for s in chosen.values()],
        executor="lite-agent",
        provenance={"composed_from": {c: s.name for c, s in chosen.items()}},
    )
    # A4：advisory 背书快照（不阻断激活；权威门是 S1 执行期质量门）
    if gateway is not None:
        cfg.eval = await _endorse(gateway, caps, cfg, session)

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
    judge = cfg.eval["judge"] if cfg.eval else "—"
    logger.info(
        "compose_agent 拼装 Agent %s 覆盖 %s（来自 %s，背书 judge=%s）",
        name,
        caps,
        cfg.skills,
        judge,
    )
    return agent


async def route_or_compose(
    session: AsyncSession,
    org_id: uuid.UUID,
    dag: PlanDag,
    *,
    gateway: ModelGateway | None = None,
) -> dict[str, str | None]:
    """逐 agent 节点路由：① 检索现有 Agent；无→② 拼 Skill 成 Agent（§5.2）。返回 node→Agent 名。

    gateway 透传给 compose_agent 做 A4 自动背书（judge 拼装结果）。
    """
    routing: dict[str, str | None] = {}
    for node in dag.nodes:
        if node.type != "agent" or not node.required_capabilities:
            continue
        agent = await select_agent(session, node.required_capabilities)
        if agent is None:
            agent = await compose_agent(
                session, org_id, node.required_capabilities, gateway=gateway
            )
        routing[node.id] = agent.name if agent is not None else None
    return routing
