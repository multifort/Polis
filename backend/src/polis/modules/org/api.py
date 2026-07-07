"""org/身份 API 路由：注册/登录/刷新/me/建城邦。"""

from __future__ import annotations

import logging
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from polis.config import get_settings
from polis.db.session import get_session, get_sessionmaker
from polis.modules.observability.audit import write_audit
from polis.modules.org import auth_rate_limit, provisioning, service
from polis.modules.org import repository as repo
from polis.modules.org.deps import CurrentOrg, CurrentUserId
from polis.modules.org.models import Role
from polis.modules.org.schemas import (
    AgentOut,
    InviteCreateIn,
    InviteOut,
    LoginIn,
    MemberOut,
    MeOut,
    OrgCreateIn,
    OrgOut,
    OrgUpdateIn,
    PasswordResetConfirmIn,
    PasswordResetRequestIn,
    PasswordResetRequestOut,
    ProvisionIn,
    ProvisionOut,
    RefreshIn,
    RegisterIn,
    RoleOut,
    TokenOut,
)

router = APIRouter(prefix="/api", tags=["identity"])
logger = logging.getLogger(__name__)

SessionDep = Annotated[AsyncSession, Depends(get_session)]


@router.post("/auth/register", response_model=TokenOut, status_code=status.HTTP_201_CREATED)
async def register(data: RegisterIn, session: SessionDep) -> TokenOut:
    try:
        return await service.register(session, data)
    except service.EmailExists as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "该邮箱已注册") from exc


async def _audit_login_failed(email: str, reason: str = "invalid_credentials") -> None:
    """登录失败审计（TD-011，防暴力破解）。独立事务——失败路径请求会回滚，故另起 session 提交。

    best-effort：审计失败不影响 401 返回；绝不记密码。
    """
    try:
        async with get_sessionmaker()() as s:
            await write_audit(s, action="auth.login_failed", actor=email, detail={"reason": reason})
            await s.commit()
    except Exception:
        logger.warning("登录失败审计写入失败（不影响 401）", exc_info=True)


@router.post("/auth/login", response_model=TokenOut)
async def login(data: LoginIn, request: Request, session: SessionDep) -> TokenOut:
    ip = request.client.host if request.client else None
    retry_after = auth_rate_limit.retry_after_seconds(data.email, ip)
    if retry_after is not None:
        await _audit_login_failed(data.email, reason="rate_limited")
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "登录尝试过多，请稍后再试",
            headers={"Retry-After": str(retry_after)},
        )
    try:
        token = await service.login(session, data)
        auth_rate_limit.record_success(data.email, ip)
        return token
    except service.InvalidCredentials as exc:
        retry_after = auth_rate_limit.record_failure(data.email, ip)
        await _audit_login_failed(data.email)
        if retry_after is not None:
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                "登录尝试过多，请稍后再试",
                headers={"Retry-After": str(retry_after)},
            ) from exc
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


@router.post("/auth/password/reset/request", response_model=PasswordResetRequestOut)
async def request_password_reset(
    data: PasswordResetRequestIn, session: SessionDep
) -> PasswordResetRequestOut:
    token = await service.request_password_reset(session, data)
    if get_settings().is_prod():
        token = None
    return PasswordResetRequestOut(reset_token=token)


@router.post("/auth/password/reset/confirm", status_code=status.HTTP_204_NO_CONTENT)
async def confirm_password_reset(data: PasswordResetConfirmIn, session: SessionDep) -> None:
    try:
        await service.confirm_password_reset(session, data)
    except service.InvalidPasswordResetToken as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "重置令牌无效或已过期") from exc


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


@router.post(
    "/orgs/{org_id}/invites", response_model=InviteOut, status_code=status.HTTP_201_CREATED
)
async def create_invite(
    org_id: uuid.UUID, data: InviteCreateIn, user_id: CurrentUserId, session: SessionDep
) -> InviteOut:
    try:
        invite = await service.create_invite(session, user_id, org_id, data)
    except service.NotOwner as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "需所有者权限") from exc
    if get_settings().is_prod():
        invite.invite_token = None
    return invite


@router.post("/invites/{token}/accept", response_model=MemberOut)
async def accept_invite(token: str, user_id: CurrentUserId, session: SessionDep) -> MemberOut:
    try:
        return await service.accept_invite(session, user_id, token)
    except service.InvalidInvite as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "邀请令牌无效或已过期") from exc
    except service.InviteEmailMismatch as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "该邀请不属于当前账号") from exc


@router.delete("/orgs/{org_id}/members/{member_user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    org_id: uuid.UUID, member_user_id: uuid.UUID, user_id: CurrentUserId, session: SessionDep
) -> None:
    try:
        await service.remove_member(session, user_id, org_id, member_user_id)
    except service.NotOwner as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "需所有者权限") from exc
    except service.MemberNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "成员不存在") from exc
    except service.CannotRemoveLastOwner as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "不能移除最后一个所有者") from exc


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
    # TD-017：注入网关让关键词走语义选预设（无 embedding/不可达时函数内回退关键词）。
    from polis.modules.model.litellm_gateway import LiteLLMGateway

    try:
        return await provisioning.provision(session, user_id, data, gateway=LiteLLMGateway())
    except provisioning.NoPresetMatch as exc:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "未匹配到预设，请换关键词或指定预设名"
        ) from exc
