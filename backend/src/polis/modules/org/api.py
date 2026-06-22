"""org/身份 API 路由：注册/登录/刷新/me/建城邦。"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from polis.db.session import get_session
from polis.modules.org import provisioning, service
from polis.modules.org import repository as repo
from polis.modules.org.deps import CurrentOrg, CurrentUserId
from polis.modules.org.models import Role
from polis.modules.org.schemas import (
    AgentOut,
    LoginIn,
    MemberOut,
    MeOut,
    OrgCreateIn,
    OrgOut,
    OrgUpdateIn,
    ProvisionIn,
    ProvisionOut,
    RefreshIn,
    RegisterIn,
    RoleOut,
    TokenOut,
)

router = APIRouter(prefix="/api", tags=["identity"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


@router.post("/auth/register", response_model=TokenOut, status_code=status.HTTP_201_CREATED)
async def register(data: RegisterIn, session: SessionDep) -> TokenOut:
    try:
        return await service.register(session, data)
    except service.EmailExists as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "该邮箱已注册") from exc


@router.post("/auth/login", response_model=TokenOut)
async def login(data: LoginIn, session: SessionDep) -> TokenOut:
    try:
        return await service.login(session, data)
    except service.InvalidCredentials as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "邮箱或密码错误") from exc


@router.post("/auth/refresh", response_model=TokenOut)
async def refresh(data: RefreshIn, session: SessionDep) -> TokenOut:
    try:
        return await service.refresh(session, data.refresh_token)
    except service.InvalidToken as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "刷新令牌无效") from exc


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(data: RefreshIn, session: SessionDep) -> None:
    """吊销 refresh 会话（幂等）。"""
    await service.logout(session, data.refresh_token)


@router.get("/me", response_model=MeOut)
async def me(user_id: CurrentUserId, session: SessionDep) -> MeOut:
    return await service.me(session, user_id)


@router.post("/orgs", response_model=OrgOut, status_code=status.HTTP_201_CREATED)
async def create_org(data: OrgCreateIn, user_id: CurrentUserId, session: SessionDep) -> OrgOut:
    return await service.create_org(session, user_id, data)


@router.patch("/orgs/{org_id}", response_model=OrgOut)
async def update_org(
    org_id: uuid.UUID, data: OrgUpdateIn, user_id: CurrentUserId, session: SessionDep
) -> OrgOut:
    try:
        return await service.update_org(session, user_id, org_id, data.name, data.description)
    except service.NotOwner as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "需所有者权限") from exc


@router.get("/orgs/{org_id}/members", response_model=list[MemberOut])
async def list_members(
    org_id: uuid.UUID, user_id: CurrentUserId, session: SessionDep
) -> list[MemberOut]:
    try:
        return await service.list_members(session, user_id, org_id)
    except service.NotOwner as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "你不属于该公司") from exc


@router.delete("/orgs/{org_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_org(org_id: uuid.UUID, user_id: CurrentUserId, session: SessionDep) -> None:
    try:
        await service.delete_org(session, user_id, org_id)
    except service.NotOwner as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "需所有者权限") from exc


@router.get("/orgs/current/roles", response_model=list[RoleOut])
async def list_current_org_roles(org: CurrentOrg, session: SessionDep) -> list[Role]:
    # 依赖 CurrentOrg 已校验成员 + 切到 RLS 上下文；查询自动按当前公司隔离
    return await repo.list_roles(session)


@router.get("/orgs/current/agents", response_model=list[AgentOut])
async def list_current_org_agents(org: CurrentOrg, session: SessionDep) -> list[dict[str, Any]]:
    # 含角色名/描述(promptSkeleton)/能力/模型，供前端节点卡与「Agent 详情」模态展示。
    return await repo.list_agents_detailed(session)


@router.post("/provision", response_model=ProvisionOut, status_code=status.HTTP_201_CREATED)
async def provision(data: ProvisionIn, user_id: CurrentUserId, session: SessionDep) -> ProvisionOut:
    # 立邦：选预设→实例化花名册。建公司故不需 CurrentOrg（此时尚无当前公司）。
    try:
        return await provisioning.provision(session, user_id, data)
    except provisioning.NoPresetMatch as exc:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "未匹配到预设，请换关键词或指定预设名"
        ) from exc
