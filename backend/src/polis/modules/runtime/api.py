"""Skill 仓库 API（TD-034）：公司主动提交/浏览自己的 Skill。"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from polis.db.session import get_session
from polis.modules.observability import repository as obs_repo
from polis.modules.observability.audit import write_audit
from polis.modules.org.deps import CurrentOrg, CurrentUserId
from polis.modules.runtime import repository as repo
from polis.modules.runtime.models import Skill

router = APIRouter(prefix="/api", tags=["skills"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


class SkillCreateIn(BaseModel):
    """公司主动提交 manual Skill 草稿。

    manual Skill 是纯 playbook，无工具/凭证/副作用；发布仍经 skill_review 人审。
    """

    name: str = Field(min_length=3, max_length=120, pattern=r"^[a-zA-Z0-9_.\-\u4e00-\u9fff]+$")
    capability: str = Field(min_length=3, max_length=160)
    content: str = Field(min_length=20, max_length=12000)


class SkillOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    kind: str
    status: str
    trust: str
    capability: str | None = None
    visibility: str
    owner_org_id: uuid.UUID | None = None
    content_preview: str | None = None
    review_status: str | None = None


def _to_out(
    skill: Skill, *, content: str | None = None, review_status: str | None = None
) -> SkillOut:
    preview = content[:240] if content else None
    return SkillOut(
        id=skill.id,
        name=skill.name,
        kind=skill.kind,
        status=skill.status,
        trust=skill.trust,
        capability=skill.capability,
        visibility=skill.visibility,
        owner_org_id=skill.owner_org_id,
        content_preview=preview,
        review_status=review_status,
    )


@router.get("/skills", response_model=list[SkillOut])
async def list_skills(
    org: CurrentOrg,
    session: SessionDep,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    mine_only: bool = False,
) -> list[SkillOut]:
    """列出当前公司可见 Skill；`mine_only=true` 时只看本公司提交/生成的私有 Skill。"""
    if status_filter is not None and status_filter not in {"draft", "published", "deprecated"}:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "非法 status")
    skills = await repo.list_visible_skills(
        session,
        org.org_id,
        status=status_filter,
        mine_only=mine_only,
    )
    versions = await repo.latest_versions_for_skills(session, [s.id for s in skills])
    approvals = await obs_repo.list_approvals(session, org.org_id, status="pending")
    review_by_ref = {
        a.ref_id: a.status for a in approvals if a.kind == "skill_review" and a.ref_id is not None
    }
    out: list[SkillOut] = []
    for skill in skills:
        version = versions.get(skill.id)
        out.append(
            _to_out(
                skill,
                content=version.content if version is not None else None,
                review_status=review_by_ref.get(str(skill.id)),
            )
        )
    return out


@router.post("/skills", response_model=SkillOut, status_code=status.HTTP_201_CREATED)
async def create_manual_skill(
    data: SkillCreateIn,
    org: CurrentOrg,
    user_id: CurrentUserId,
    session: SessionDep,
) -> SkillOut:
    """提交公司私有 manual Skill 草稿，并创建一条 skill_review 审批。

    这里不自动发布：公司主动上传的 playbook 也要经 owner/approver 背书，避免绕过既有信任分层。
    """
    if await repo.get_any_skill_by_name(session, data.name) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "技能名已存在")
    skill = await repo.create_manual_skill_draft(
        session,
        org.org_id,
        name=data.name,
        capability=data.capability,
        content=data.content,
        owner=str(user_id),
    )
    await obs_repo.create_approval(
        session,
        org_id=org.org_id,
        kind="skill_review",
        ref_id=str(skill.id),
        payload={
            "capability": data.capability,
            "skill_name": data.name,
            "kind": "manual",
            "source": "user_submitted",
            "preview": data.content[:240],
        },
    )
    await write_audit(
        session,
        action="skill.create_draft",
        actor=str(user_id),
        org_id=org.org_id,
        target=str(skill.id),
        detail={"name": data.name, "capability": data.capability},
    )
    return _to_out(skill, content=data.content, review_status="pending")
