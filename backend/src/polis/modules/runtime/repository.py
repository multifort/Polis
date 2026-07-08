"""runtime 数据访问层。集中 SQL（12 C 分层）。skill 为全局表（私有项带 owner_org_id）。"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from polis.db.org_scoped import visible_clause
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


async def get_visible_skill(
    session: AsyncSession, org_id: uuid.UUID, skill_id: uuid.UUID
) -> Skill | None:
    """按可见性取 Skill（自己私有 ∪ public）。"""
    skill: Skill | None = await session.scalar(
        select(Skill).where(Skill.id == skill_id, visible_clause(Skill, org_id))
    )
    return skill


async def get_owned_skill_by_name(
    session: AsyncSession, org_id: uuid.UUID, name: str
) -> Skill | None:
    """同一 org 内按 name 查自有 Skill。Skill.name 仍是全局唯一，API 层另处理全局冲突。"""
    skill: Skill | None = await session.scalar(
        select(Skill).where(Skill.owner_org_id == org_id, Skill.name == name)
    )
    return skill


async def get_any_skill_by_name(session: AsyncSession, name: str) -> Skill | None:
    """全局按 name 查重（数据库也有 unique 约束；这里用于返回友好 409）。"""
    skill: Skill | None = await session.scalar(select(Skill).where(Skill.name == name))
    return skill


async def get_owned_skill_for_update(
    session: AsyncSession,
    org_id: uuid.UUID,
    skill_id: uuid.UUID,
) -> tuple[Skill, SkillVersion | None] | None:
    """取本 org 拥有的 Skill 及最新版本，用于编辑草稿。"""
    skill: Skill | None = await session.scalar(
        select(Skill).where(Skill.id == skill_id, Skill.owner_org_id == org_id)
    )
    if skill is None:
        return None
    version = await session.scalar(
        select(SkillVersion)
        .where(SkillVersion.skill_id == skill.id)
        .order_by(SkillVersion.version.desc())
    )
    return skill, version


async def update_manual_skill_draft(
    session: AsyncSession,
    skill: Skill,
    version: SkillVersion | None,
    *,
    name: str | None = None,
    capability: str | None = None,
    content: str | None = None,
) -> SkillVersion:
    """编辑公司私有 manual 草稿。发布后的 Skill 不在这里改，必须走新版/评审策略。"""
    if name is not None:
        skill.name = name
    if capability is not None:
        skill.capability = capability
    if version is None:
        version = SkillVersion(skill_id=skill.id, version="v1", content=content or "")
        session.add(version)
    elif content is not None:
        version.content = content
    await session.flush()
    return version


async def deprecate_owned_skill(
    session: AsyncSession,
    org_id: uuid.UUID,
    skill_id: uuid.UUID,
) -> Skill | None:
    """停用本 org 拥有的已发布 Skill。停用后不再进入 available_capabilities。"""
    skill: Skill | None = await session.scalar(
        select(Skill).where(
            Skill.id == skill_id,
            Skill.owner_org_id == org_id,
            Skill.status == "published",
        )
    )
    if skill is None:
        return None
    skill.status = "deprecated"
    await session.flush()
    return skill


async def create_manual_skill_draft(
    session: AsyncSession,
    org_id: uuid.UUID,
    *,
    name: str,
    capability: str,
    content: str,
    owner: str | None = None,
) -> Skill:
    """公司主动提交 manual Skill：先落私有 draft，等待 skill_review 审批发布。"""
    skill = Skill(
        name=name,
        kind="manual",
        status="draft",
        trust="private",
        capability=capability,
        owner=owner,
        owner_org_id=org_id,
        visibility="org",
    )
    session.add(skill)
    await session.flush()
    session.add(SkillVersion(skill_id=skill.id, version="v1", content=content))
    await session.flush()
    return skill


async def latest_versions_for_skills(
    session: AsyncSession, skill_ids: list[uuid.UUID]
) -> dict[uuid.UUID, SkillVersion]:
    """批量取每个 Skill 的最新版本（当前版本号为 vN 字符串，按降序与既有逻辑保持一致）。"""
    if not skill_ids:
        return {}
    rows = await session.execute(
        select(SkillVersion)
        .where(SkillVersion.skill_id.in_(skill_ids))
        .order_by(SkillVersion.skill_id, SkillVersion.version.desc())
    )
    latest: dict[uuid.UUID, SkillVersion] = {}
    for sv in rows.scalars().all():
        latest.setdefault(sv.skill_id, sv)
    return latest


async def list_visible_skills(
    session: AsyncSession,
    org_id: uuid.UUID,
    *,
    status: str | None = None,
    mine_only: bool = False,
) -> list[Skill]:
    """列出当前 org 可见 Skill；mine_only 时仅列自有 Skill（含 draft）。"""
    scope = Skill.owner_org_id == org_id if mine_only else visible_clause(Skill, org_id)
    q = select(Skill).where(scope)
    if status:
        q = q.where(Skill.status == status)
    rows = await session.scalars(q.order_by(Skill.name))
    return list(rows.all())
