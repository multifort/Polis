"""A3 编配生成 + A4 自动背书：节点无现成 Agent → 拼已审 Skill 成 Agent，eval 背书后启用。

设计：docs/design/v2/01 §5.2–5.4 / §6 / §13.2 / §14.5（ADR-0010 角色驱动主干 + 任务驱动弹性）。
洞察：Skill 是唯一的「新代码」资产；Agent 只是「已审 Skill 之上的配置拼装」。因此拼装
已有 Skill 成 Agent **不产生新代码 → 可自动生成 + 自动 eval 背书、不卡人审**；只有「某能力连
Skill 都没有」才撞人审墙（生成 Skill 草稿走审核——A3 暂不做，缺 Skill 即返 None）。
A4 自动背书 + TD-033 试产出硬门控：拼装后让 Agent **试产出**一份示例结果（带技能 playbook 内容）
再 judge，judge≥τ 才置 active 启用、否则落 draft 留观测（硬降级）。比早期「只看技能名」的 advisory
判定可靠得多。运行期仍有 S1 质量门兜底（对真实节点产出 judge→needs_rework）。
"""

from __future__ import annotations

import datetime as dt
import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from polis.config import get_settings
from polis.db.org_scoped import select_org_scoped, visible_clause
from polis.modules.model.gateway import ChatMessage, ModelGateway, resolve_model
from polis.modules.observability import evaluator
from polis.modules.org.models import Agent, AgentCapability, AgentVersion
from polis.modules.org.schemas import AgentConfig
from polis.modules.planner.router import select_agent
from polis.modules.planner.schemas import PlanDag
from polis.modules.planner.skillgen import generate_skill_draft
from polis.modules.runtime.models import Skill, SkillVersion

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
_TRIAL_PREVIEW = 200


async def _skill_contents(session: AsyncSession, skill_names: list[str]) -> list[str]:
    """载入绑定技能的 playbook 正文（让试产出真正「用」技能内容，而非只看技能名）。"""
    if not skill_names:
        return []
    rows = (
        await session.execute(
            select(Skill.name, SkillVersion.content)
            .join(SkillVersion, SkillVersion.skill_id == Skill.id)
            .where(Skill.name.in_(skill_names))
        )
    ).all()
    return [f"【{name}】\n{content}" for name, content in rows if content]


async def _trial_endorse(
    gateway: ModelGateway, caps: list[str], cfg: AgentConfig, session: AsyncSession
) -> dict[str, object]:
    """A4/TD-033 自动背书：让拼装出的 Agent **试产出**一份示例结果再 judge（强信号，可硬门控）。

    比 advisory 配置判定可靠——judge 看的是 Agent 真实产出（带上技能 playbook 内容），而非技能名。
    两次 LLM 调用（试产出 + 评分），无副作用（不落 envelope/调用日志）。失败由调用方硬降级。
    """
    model = await resolve_model(session, get_settings().default_chat_model)
    playbooks = await _skill_contents(session, cfg.skills)
    sys = cfg.prompt + ("\n\n可用技能手册：\n" + "\n---\n".join(playbooks) if playbooks else "")
    trial_in = (
        f"请就你负责的能力【{'、'.join(caps)}】，针对一个典型场景给出一份示例产出："
        "结构化、可执行、有依据，简洁即可。"
    )
    trial_out = (
        await gateway.chat(
            model,
            [ChatMessage(role="system", content=sys), ChatMessage(role="user", content=trial_in)],
        )
    ).content or ""
    criteria = f"该产出是否合格地体现了能力【{'、'.join(caps)}】，结构化、可执行、有依据"
    res = await evaluator.score(gateway, model, trial_out, acceptance_criteria=criteria)
    return {
        "judge": res.judge_score,
        "passed": res.judge_score >= _EVAL_TAU,
        "at": dt.datetime.now(dt.UTC).isoformat(),
        "kind": "trial_output",
        "trial_preview": trial_out[:_TRIAL_PREVIEW],
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
    """拼装一个覆盖 caps 的 Agent：每能力取一个 published Skill，全有则**试产出 eval 背书**后启用。

    A4/TD-033：给了 gateway → 让拼装 Agent 试产出一份示例结果再 judge（强信号）。judge≥τ → active；
    <τ → 落 draft（不可用、留观测）+ 返回 None（硬降级）。无 gateway（TEI 不可达/测试）→ 跳过、直接
    active。幂等：同能力集已建过的 Agent——active 复用、draft 不重建（返 None）。缺 Skill → 见上。
    """
    caps = list(dict.fromkeys(caps))  # 去重保序
    if not caps:
        return None

    name = _compose_name(caps)
    # 显式 org 过滤（请求外不依赖 RLS）。按名取任一状态：active 复用、draft 不重建（避唯一约束）
    existing = await session.scalar(select_org_scoped(Agent, org_id).where(Agent.name == name))
    if existing is not None:
        return existing if existing.status == "active" else None

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
    # A4/TD-033：试产出 eval 背书 → 硬门控（judge≥τ active / <τ draft）。无 gateway → 跳过激活。
    endorsed = True
    if gateway is not None:
        cfg.eval = await _trial_endorse(gateway, caps, cfg, session)
        endorsed = bool(cfg.eval["passed"])

    agent = Agent(
        org_id=org_id,
        role_id=None,  # 临时组队不挂常设角色（高频复用时再晋升，§5.1）
        name=name,
        source="generated",
        status="active" if endorsed else "draft",  # 试产出过阈值才启用（§5.3 + TD-033）
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
    if not endorsed:
        logger.info("compose_agent %s 试产出背书未过(judge=%s<%.2f)→draft", name, judge, _EVAL_TAU)
        return None
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
