"""Skill 仓库 API（TD-034）：公司主动提交/浏览自己的 Skill。"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from polis.db.session import get_session
from polis.modules.observability import repository as obs_repo
from polis.modules.observability.audit import write_audit
from polis.modules.org.deps import CurrentOrg, CurrentUserId, OrgContext, require_role
from polis.modules.planner.skillgen import ToolSkillSandboxError, create_tool_skill_draft
from polis.modules.runtime import repository as repo
from polis.modules.runtime.mcp import McpToolCallError
from polis.modules.runtime.models import Skill

router = APIRouter(prefix="/api", tags=["skills"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
ApproverOrg = Annotated[OrgContext, Depends(require_role("owner", "approver"))]


class SkillCreateIn(BaseModel):
    """公司主动提交 manual Skill 草稿。

    manual Skill 是纯 playbook，无工具/凭证/副作用；发布仍经 skill_review 人审。
    """

    name: str = Field(min_length=3, max_length=120, pattern=r"^[a-zA-Z0-9_.\-\u4e00-\u9fff]+$")
    capability: str = Field(min_length=3, max_length=160)
    content: str = Field(min_length=20, max_length=12000)


class SkillUpdateIn(BaseModel):
    """编辑公司私有 manual Skill 草稿。发布后的版本不允许直接改。"""

    name: str | None = Field(
        default=None, min_length=3, max_length=120, pattern=r"^[a-zA-Z0-9_.\-\u4e00-\u9fff]+$"
    )
    capability: str | None = Field(default=None, min_length=3, max_length=160)
    content: str | None = Field(default=None, min_length=20, max_length=12000)


class SkillRevisionIn(BaseModel):
    """从已发布 manual Skill 派生新版草稿。"""

    name: str = Field(min_length=3, max_length=120, pattern=r"^[a-zA-Z0-9_.\-\u4e00-\u9fff]+$")
    capability: str | None = Field(default=None, min_length=3, max_length=160)
    content: str = Field(min_length=20, max_length=12000)


class ToolSkillCreateIn(BaseModel):
    """公司主动提交 tool Skill 草稿。

    tool Skill 有外部调用/副作用风险，必须复用最小权限 + 沙箱闸，且仍需 skill_review 人审发布。
    """

    name: str = Field(min_length=3, max_length=120, pattern=r"^[a-zA-Z0-9_.\-\u4e00-\u9fff]+$")
    capability: str = Field(min_length=3, max_length=160)
    mcp_server: str = Field(min_length=1, max_length=120)
    tool: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=20, max_length=12000)
    io_schema: dict[str, Any] = Field(default_factory=dict)
    permissions: dict[str, Any] = Field(default_factory=dict)
    sandbox_args: dict[str, Any] = Field(default_factory=dict)
    http_endpoint: str | None = Field(default=None, max_length=2048)
    mcp_config: dict[str, Any] | None = None
    timeout_seconds: float = Field(default=5.0, ge=0.1, le=60.0)


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
    pending_revision: dict[str, Any] | None = None


def _to_out(
    skill: Skill,
    *,
    content: str | None = None,
    review_status: str | None = None,
    pending_revision: dict[str, Any] | None = None,
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
        pending_revision=pending_revision,
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
    pending_revision_by_source: dict[str, dict[str, Any]] = {}
    for approval in approvals:
        if approval.kind != "skill_review" or approval.ref_id is None:
            continue
        payload = approval.payload or {}
        if payload.get("source") != "revision":
            continue
        source_skill_id = payload.get("source_skill_id")
        if not isinstance(source_skill_id, str):
            continue
        pending_revision_by_source[source_skill_id] = {
            "draft_skill_id": approval.ref_id,
            "draft_skill_name": payload.get("skill_name"),
            "review_status": approval.status,
        }
    out: list[SkillOut] = []
    for skill in skills:
        version = versions.get(skill.id)
        out.append(
            _to_out(
                skill,
                content=version.content if version is not None else None,
                review_status=review_by_ref.get(str(skill.id)),
                pending_revision=pending_revision_by_source.get(str(skill.id)),
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


@router.post("/skills/tool", response_model=SkillOut, status_code=status.HTTP_201_CREATED)
async def create_tool_skill(
    data: ToolSkillCreateIn,
    org: CurrentOrg,
    user_id: CurrentUserId,
    session: SessionDep,
) -> SkillOut:
    """提交公司私有 tool Skill 草稿。

    这里不接受自动发布：即便沙箱通过，也只证明工具声明可执行；是否成为 verified 能力仍由审批人决定。
    """
    if await repo.get_any_skill_by_name(session, data.name) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "技能名已存在")
    try:
        skill = await create_tool_skill_draft(
            session,
            org.org_id,
            data.capability,
            name=data.name,
            mcp_server=data.mcp_server,
            tool=data.tool,
            description=data.description,
            io_schema=data.io_schema,
            permissions=data.permissions,
            sandbox_args=data.sandbox_args,
            http_endpoint=data.http_endpoint,
            mcp_config=data.mcp_config,
            timeout_seconds=data.timeout_seconds,
        )
    except (ToolSkillSandboxError, McpToolCallError) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    await write_audit(
        session,
        action="skill.create_tool_draft",
        actor=str(user_id),
        org_id=org.org_id,
        target=str(skill.id),
        detail={"name": data.name, "capability": data.capability, "tool": data.tool},
    )
    version = (await repo.latest_versions_for_skills(session, [skill.id])).get(skill.id)
    return _to_out(
        skill,
        content=version.content if version is not None else data.description,
        review_status="pending" if skill.status == "draft" else None,
    )


@router.patch("/skills/{skill_id}", response_model=SkillOut)
async def update_manual_skill(
    skill_id: uuid.UUID,
    data: SkillUpdateIn,
    org: CurrentOrg,
    user_id: CurrentUserId,
    session: SessionDep,
) -> SkillOut:
    """编辑公司私有 manual Skill 草稿，并保持/重建 skill_review 审批。

    只允许编辑 draft：published/verified Skill 已进入编配可用能力，直接改写会绕过人审与复现语义。
    """
    if data.name is None and data.capability is None and data.content is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "至少提供一个待更新字段")
    owned = await repo.get_owned_skill_for_update(session, org.org_id, skill_id)
    if owned is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Skill 不存在")
    skill, version = owned
    if skill.kind != "manual" or skill.status != "draft":
        raise HTTPException(status.HTTP_409_CONFLICT, "仅可编辑待审 manual Skill 草稿")
    if data.name is not None and data.name != skill.name:
        existing = await repo.get_any_skill_by_name(session, data.name)
        if existing is not None and existing.id != skill.id:
            raise HTTPException(status.HTTP_409_CONFLICT, "技能名已存在")
    version = await repo.update_manual_skill_draft(
        session,
        skill,
        version,
        name=data.name,
        capability=data.capability,
        content=data.content,
    )
    content = version.content or ""
    pending = await obs_repo.get_pending_approval_by_ref(
        session, org.org_id, kind="skill_review", ref_id=str(skill.id)
    )
    payload = {
        "capability": skill.capability,
        "skill_name": skill.name,
        "kind": "manual",
        "source": "user_submitted",
        "preview": content[:240],
        "updated_by": str(user_id),
    }
    if pending is None:
        await obs_repo.create_approval(
            session,
            org_id=org.org_id,
            kind="skill_review",
            ref_id=str(skill.id),
            payload=payload,
        )
    else:
        pending.payload = payload
    await write_audit(
        session,
        action="skill.update_draft",
        actor=str(user_id),
        org_id=org.org_id,
        target=str(skill.id),
        detail={"name": skill.name, "capability": skill.capability},
    )
    return _to_out(skill, content=content, review_status="pending")


@router.post("/skills/{skill_id}/deprecate", response_model=SkillOut)
async def deprecate_skill(
    skill_id: uuid.UUID,
    org: ApproverOrg,
    user_id: CurrentUserId,
    session: SessionDep,
) -> SkillOut:
    """停用本公司已发布 Skill。

    停用不会删除历史版本/运行复现信息，只让该 Skill 退出后续 `published` 能力检索集合。
    """
    skill = await repo.deprecate_owned_skill(session, org.org_id, skill_id)
    if skill is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "仅可停用本公司已发布 Skill")
    versions = await repo.latest_versions_for_skills(session, [skill.id])
    await write_audit(
        session,
        action="skill.deprecate",
        actor=str(user_id),
        org_id=org.org_id,
        target=str(skill.id),
        detail={"name": skill.name, "capability": skill.capability},
    )
    version = versions.get(skill.id)
    return _to_out(skill, content=version.content if version is not None else None)


@router.post(
    "/skills/{skill_id}/revisions",
    response_model=SkillOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_skill_revision(
    skill_id: uuid.UUID,
    data: SkillRevisionIn,
    org: ApproverOrg,
    user_id: CurrentUserId,
    session: SessionDep,
) -> SkillOut:
    """为本公司已发布 manual Skill 创建新版草稿。

    当前数据模型不在同一 Skill 上挂未审 v2，避免运行时按 latest version 误读未审核内容。
    新版以新的私有 draft Skill 进入 skill_review；发布后可手动停用旧版。
    """
    source = await repo.get_visible_skill(session, org.org_id, skill_id)
    if source is None or source.owner_org_id != org.org_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Skill 不存在")
    if source.kind != "manual" or source.status != "published":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "仅可为本公司已发布 manual Skill 创建新版草稿",
        )
    if await repo.get_any_skill_by_name(session, data.name) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "技能名已存在")
    capability = data.capability or source.capability
    if not capability:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "缺少能力 key")
    skill = await repo.create_manual_skill_draft(
        session,
        org.org_id,
        name=data.name,
        capability=capability,
        content=data.content,
        owner=str(user_id),
    )
    await obs_repo.create_approval(
        session,
        org_id=org.org_id,
        kind="skill_review",
        ref_id=str(skill.id),
        payload={
            "capability": skill.capability,
            "skill_name": skill.name,
            "kind": "manual",
            "source": "revision",
            "source_skill_id": str(source.id),
            "source_skill_name": source.name,
            "preview": data.content[:240],
        },
    )
    await write_audit(
        session,
        action="skill.create_revision",
        actor=str(user_id),
        org_id=org.org_id,
        target=str(skill.id),
        detail={"source_skill_id": str(source.id), "name": skill.name},
    )
    return _to_out(skill, content=data.content, review_status="pending")
