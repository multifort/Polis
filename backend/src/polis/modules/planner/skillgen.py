"""TD-032 Skill 生成链：缺 Skill 的能力 → LLM 生成 manual 草稿 → 撞人审墙（不自动发布）。

设计：docs/design/v2/01 §5.4 / §14.5（生成停点）。**安全红线（CLAUDE.md §4.6）**：AI 生成的
Skill 默认不可信——本模块只产 `status='draft'/trust='private'` 草稿并建 `skill_review` 审批，
**绝不自动发布/激活**；只有人审通过（approval decide approve）才 `publish_skill` 置 published/
verified，其能力随之进入 `available_capabilities`（ADR-0009 背书链），下次即可拼装。
仅做 manual（提示词/playbook）草稿；tool/MCP 草稿 + 沙箱试跑留作后续。
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from polis.config import get_settings
from polis.modules.model.gateway import ChatMessage, ModelGateway, resolve_model
from polis.modules.observability import repository as obs_repo
from polis.modules.runtime.models import Skill, SkillVersion

logger = logging.getLogger(__name__)

_PREVIEW_CHARS = 240

_SYSTEM = (
    "你是资深的 Agent 技能作者。请为给定「能力 key」编写一份**操作手册（playbook）**，供一个 "
    "lite-agent 据此完成该能力对应的工作。要求：分步骤、可执行、说明输入/输出与注意事项；"
    "只输出手册正文，不要寒暄、不要代码围栏。"
)


async def generate_skill_draft(
    session: AsyncSession, org_id: uuid.UUID, cap: str, gateway: ModelGateway
) -> Skill:
    """为缺 Skill 的能力 cap 生成 manual 草稿 + skill_review 审批（幂等，绝不自动发布）。

    幂等：本 org 已有该 cap 的 draft → 直接返回（不重复生成/重复建审批）。
    """
    existing = await session.scalar(
        select(Skill).where(
            Skill.capability == cap,
            Skill.owner_org_id == org_id,
            Skill.status == "draft",
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
        kind="manual",
        status="draft",  # 安全红线：草稿，绝不自动 published
        trust="private",
        capability=cap,
        owner_org_id=org_id,
        visibility="org",
    )
    session.add(skill)
    await session.flush()
    session.add(SkillVersion(skill_id=skill.id, version="v1", content=content))

    # 撞人审墙：建 skill_review 审批（人审通过才 publish_skill）
    await obs_repo.create_approval(
        session,
        org_id=org_id,
        kind="skill_review",
        ref_id=str(skill.id),
        payload={"capability": cap, "skill_name": name, "preview": content[:_PREVIEW_CHARS]},
    )
    await session.flush()
    logger.info("generate_skill_draft 为能力 %s 生成草稿 %s + 待人审", cap, name)
    return skill


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
