"""org/身份 API 路由：注册/登录/刷新/me/建城邦。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from polis.db.session import get_session
from polis.modules.org import repository as repo
from polis.modules.org import service
from polis.modules.org.deps import CurrentOrg, CurrentUserId
from polis.modules.org.models import Role
from polis.modules.org.schemas import (
    LoginIn,
    MeOut,
    OrgCreateIn,
    OrgOut,
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


@router.get("/me", response_model=MeOut)
async def me(user_id: CurrentUserId, session: SessionDep) -> MeOut:
    return await service.me(session, user_id)


@router.post("/orgs", response_model=OrgOut, status_code=status.HTTP_201_CREATED)
async def create_org(data: OrgCreateIn, user_id: CurrentUserId, session: SessionDep) -> OrgOut:
    return await service.create_org(session, user_id, data)


@router.get("/orgs/current/roles", response_model=list[RoleOut])
async def list_current_org_roles(org: CurrentOrg, session: SessionDep) -> list[Role]:
    # 依赖 CurrentOrg 已校验成员 + 切到 RLS 上下文；查询自动按当前公司隔离
    return await repo.list_roles(session)
