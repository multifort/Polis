"""runtime 数据访问层。集中 SQL（12 C 分层）。skill 为全局表（无 org_id）。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from polis.modules.runtime.models import Skill, SkillVersion


async def get_skill_with_version(
    session: AsyncSession, name: str, version: str | None = None
) -> tuple[Skill, SkillVersion] | None:
    """按 name(+可选 version) 取技能及其版本；version 省略时取版本号倒序第一条。"""
    skill = await session.scalar(select(Skill).where(Skill.name == name))
    if skill is None:
        return None
    q = select(SkillVersion).where(SkillVersion.skill_id == skill.id)
    q = (
        q.where(SkillVersion.version == version)
        if version
        else q.order_by(SkillVersion.version.desc())
    )
    sv = await session.scalar(q)
    if sv is None:
        return None
    return skill, sv
