"""Skill 生成链（TD-032）+ 风险分级放行：缺 Skill 的能力 → LLM 生成草稿 → 按风险定放行路径。

设计：docs/design/v2/01 §5.4 / §6.2 / §14.5 + 用户决策「风险分级放行」。**安全红线**（§4.6）：
副作用来自「工具」，不来自「提示词」。据此分级：
- `manual`（playbook：纯提示词、无工具/权限/副作用）= 低风险 → **自动 eval 门（试用+judge）过即自动
  published（trust=community），无人卡** → 任务同轮即可用，满足自治诉求。
- `tool`（MCP 工具：真·新代码/外部调用/凭证/危险动作）= 高风险 → **保留人审墙 + 沙箱**（draft +
  skill_review，绝不自动发布）。本模块暂只生成 manual；tool 生成 + 沙箱留作后续。
自动放行仍留审计痕（一条 status=approved、decided_by=NULL、payload.auto_eval 的 approval）。
"""

from __future__ import annotations

import datetime as dt
import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from polis.config import get_settings
from polis.modules.model.gateway import ChatMessage, ModelGateway, ResolvedModel, resolve_model
from polis.modules.observability import repository as obs_repo
from polis.modules.observability.evaluator import score
from polis.modules.observability.models import Approval
from polis.modules.runtime.models import Skill, SkillVersion

logger = logging.getLogger(__name__)

_PREVIEW_CHARS = 240
_SKILL_EVAL_TAU = 0.6  # manual skill 自动放行的 judge 阈值

_SYSTEM = (
    "你是资深的 Agent 技能作者。请为给定「能力 key」编写一份**操作手册（playbook）**，供一个 "
    "lite-agent 据此完成该能力对应的工作。要求：分步骤、可执行、说明输入/输出与注意事项；"
    "只输出手册正文，不要寒暄、不要代码围栏。"
)


async def _auto_eval(gateway: ModelGateway, model: ResolvedModel, cap: str, content: str) -> float:
    """manual skill 自动门（沙箱试用）：按 playbook 试产出一份示例结果再 judge，返回 0~1 分。

    manual 无代码/工具 → 「试跑」即让模型遵手册产一份示例产出（无副作用），judge 其是否合格。
    """
    trial = (
        await gateway.chat(
            model,
            [
                ChatMessage(role="system", content=f"请严格遵循以下操作手册完成工作：\n{content}"),
                ChatMessage(
                    role="user",
                    content=f"针对能力【{cap}】的一个典型场景，给出一份示例产出：结构化、可执行、有依据。",
                ),
            ],
        )
    ).content or ""
    res = await score(
        gateway,
        model,
        trial,
        acceptance_criteria=f"该产出是否合格地体现了能力【{cap}】，结构化、可执行、有依据",
    )
    return res.judge_score


async def generate_skill_draft(
    session: AsyncSession, org_id: uuid.UUID, cap: str, gateway: ModelGateway
) -> Skill:
    """为缺 Skill 的能力 cap 生成 manual 草稿；自动 eval 过 → 自动 published，否则撞人审墙。

    幂等：本 org 已有该 cap 的 draft/published → 直接返回（不重复生成/建审批）。
    """
    existing = await session.scalar(
        select(Skill).where(
            Skill.capability == cap,
            Skill.owner_org_id == org_id,
            Skill.status.in_(("draft", "published")),
        )
    )
    if existing is not None:
        return existing

    model = await resolve_model(session, get_settings().default_chat_model)
    msgs = [
        ChatMessage(role="system", content=_SYSTEM),
        ChatMessage(role="user", content=f"能力 key：{cap}\n请编写该能力的操作手册。"),
    ]
    content = (await gateway.chat(model, msgs)).content or ""

    name = f"gen.{cap}.{uuid.uuid4().hex[:6]}"
    skill = Skill(
        name=name,
        kind="manual",  # 纯提示词、无工具/副作用
        status="draft",
        trust="private",
        capability=cap,
        owner_org_id=org_id,
        visibility="org",
    )
    session.add(skill)
    await session.flush()
    session.add(SkillVersion(skill_id=skill.id, version="v1", content=content))
    await session.flush()

    # 风险分级放行：manual 过自动 eval → 自动发布（community/无人卡）；否则撞人审墙
    judge = await _auto_eval(gateway, model, cap, content)
    payload = {"capability": cap, "skill_name": name, "preview": content[:_PREVIEW_CHARS]}
    if judge >= _SKILL_EVAL_TAU:
        skill.status = "published"
        skill.trust = "community"  # 机器背书放行（低于人审 verified，但已 published 可用）
        # 审计痕：一条自动通过的 approval（decided_by=NULL 表示机器放行）
        session.add(
            Approval(
                org_id=org_id,
                kind="skill_review",
                ref_id=str(skill.id),
                status="approved",
                payload={**payload, "auto_eval": judge},
                decided_at=dt.datetime.now(dt.UTC),
            )
        )
        await session.flush()
        logger.info(
            "generate_skill_draft %s 自动 eval 过(judge=%.2f)→ 自动发布 community", name, judge
        )
    else:
        await obs_repo.create_approval(
            session,
            org_id=org_id,
            kind="skill_review",
            ref_id=str(skill.id),
            payload={**payload, "auto_eval": judge},
        )
        await session.flush()
        logger.info("generate_skill_draft %s 自动 eval 未过(judge=%.2f)→ 撞人审墙", name, judge)
    return skill


_TAU_DEDUP = 0.86  # 能力语义去重阈值（design §14.6）：≥τ 视为同义、复用已有 key


async def resolve_capability(
    session: AsyncSession, gateway: ModelGateway, name: str, description: str = ""
) -> str | None:
    """TD-030/§14.4 能力语义去重：把「拟新增能力」解析到最近的已有 capability key。

    embed(name+description) → 最近已有能力 cosine ≥ τ_dedup → 返回其 key（复用，防同义爆炸）；
    否则 None（确为新能力，由调用方走登记/生成链）。embed 失败/无回填 → None。
    **仅用于能力登记期去重**，不用于执行期路由（能力 key 是契约，执行按精确匹配）。
    """
    from polis.modules.planner import repository as planner_repo

    try:
        vec = (await gateway.embed([f"{name} {description}".strip()]))[0]
    except Exception:
        logger.warning("resolve_capability embedding 失败", exc_info=True)
        return None
    if vec is None:
        return None
    ranked = await planner_repo.rank_capabilities_by_vector(session, vec, limit=1)
    if ranked and ranked[0][1] >= _TAU_DEDUP:
        return ranked[0][0].key
    return None


async def publish_skill(session: AsyncSession, org_id: uuid.UUID, skill_id: uuid.UUID) -> bool:
    """人审通过后发布草稿 Skill（published/verified）。仅发布本 org 拥有的 draft。返回是否发布。

    发布后该 Skill 的能力即进入 available_capabilities（ADR-0009），编配器下次可自动拼装。
    """
    skill = await session.scalar(
        select(Skill).where(Skill.id == skill_id, Skill.owner_org_id == org_id)
    )
    if skill is None or skill.status != "draft":
        return False
    skill.status = "published"
    skill.trust = "verified"  # 人审 = 背书来源（§14.4）
    await session.flush()
    logger.info("publish_skill 发布 %s（能力 %s）→ published", skill.name, skill.capability)
    return True
