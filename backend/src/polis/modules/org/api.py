"""org/身份 API 路由：注册/登录/刷新/me/建城邦。"""

from __future__ import annotations

import logging
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from polis.config import get_settings
from polis.core.mail import MailDeliveryError
from polis.db.session import get_session, get_sessionmaker
from polis.modules.model.models import ModelCatalog
from polis.modules.observability.audit import write_audit
from polis.modules.org import auth_rate_limit, provisioning, service
from polis.modules.org import repository as repo
from polis.modules.org.deps import CurrentOrg, CurrentUserId, OrgContext, require_role
from polis.modules.org.models import Role
from polis.modules.org.schemas import (
    AgentModelUpdateIn,
    AgentOut,
    InviteCreateIn,
    InviteOut,
    LoginIn,
    MemberOut,
    MemberRoleUpdateIn,
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
OptionalRefreshBody = Annotated[RefreshIn | None, Body()]
OwnerOrg = Annotated[OrgContext, Depends(require_role("owner"))]

ACCESS_COOKIE = "polis_access"
REFRESH_COOKIE = "polis_refresh"


def _set_auth_cookies(response: Response, tokens: TokenOut) -> None:
    settings = get_settings()
    secure = settings.is_prod()
    response.set_cookie(
        ACCESS_COOKIE,
        tokens.access_token,
        max_age=settings.access_ttl_min * 60,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
    )
    response.set_cookie(
        REFRESH_COOKIE,
        tokens.refresh_token,
        max_age=settings.refresh_ttl_days * 24 * 60 * 60,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
    )


def _clear_auth_cookies(response: Response) -> None:
    secure = get_settings().is_prod()
    response.delete_cookie(ACCESS_COOKIE, path="/", secure=secure, samesite="lax")
    response.delete_cookie(REFRESH_COOKIE, path="/", secure=secure, samesite="lax")


def _refresh_from_body_or_cookie(data: RefreshIn | None, request: Request) -> str:
    token = data.refresh_token if data is not None else request.cookies.get(REFRESH_COOKIE)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "刷新令牌无效")
    return token


@router.post("/auth/register", response_model=TokenOut, status_code=status.HTTP_201_CREATED)
async def register(data: RegisterIn, response: Response, session: SessionDep) -> TokenOut:
    try:
        tokens = await service.register(session, data)
    except service.EmailExists as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "该邮箱已注册") from exc
    _set_auth_cookies(response, tokens)
    return tokens


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


async def _rate_limit_retry_after(email: str, ip: str | None) -> int | None:
    async with get_sessionmaker()() as s:
        retry_after = await auth_rate_limit.retry_after_seconds_db(s, email, ip)
        await s.commit()
        return retry_after


async def _record_login_failure(email: str, ip: str | None) -> int | None:
    async with get_sessionmaker()() as s:
        retry_after = await auth_rate_limit.record_failure_db(s, email, ip)
        await s.commit()
        return retry_after


async def _record_login_success(email: str, ip: str | None) -> None:
    async with get_sessionmaker()() as s:
        await auth_rate_limit.record_success_db(s, email, ip)
        await s.commit()


@router.post("/auth/login", response_model=TokenOut)
async def login(
    data: LoginIn, request: Request, response: Response, session: SessionDep
) -> TokenOut:
    ip = request.client.host if request.client else None
    retry_after = await _rate_limit_retry_after(data.email, ip)
    if retry_after is not None:
        await _audit_login_failed(data.email, reason="rate_limited")
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "登录尝试过多，请稍后再试",
            headers={"Retry-After": str(retry_after)},
        )
    try:
        token = await service.login(session, data)
        await _record_login_success(data.email, ip)
        _set_auth_cookies(response, token)
        return token
    except service.InvalidCredentials as exc:
        retry_after = await _record_login_failure(data.email, ip)
        await _audit_login_failed(data.email)
        if retry_after is not None:
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                "登录尝试过多，请稍后再试",
                headers={"Retry-After": str(retry_after)},
            ) from exc
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "邮箱或密码错误") from exc


@router.post("/auth/refresh", response_model=TokenOut)
async def refresh(
    request: Request,
    response: Response,
    session: SessionDep,
    data: OptionalRefreshBody = None,
) -> TokenOut:
    try:
        tokens = await service.refresh(session, _refresh_from_body_or_cookie(data, request))
    except service.InvalidToken as exc:
        _clear_auth_cookies(response)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "刷新令牌无效") from exc
    _set_auth_cookies(response, tokens)
    return tokens


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    response: Response,
    session: SessionDep,
    data: OptionalRefreshBody = None,
) -> None:
    """吊销 refresh 会话（幂等）。"""
    token = data.refresh_token if data is not None else request.cookies.get(REFRESH_COOKIE)
    if token:
        await service.logout(session, token)
    _clear_auth_cookies(response)


@router.post("/auth/password/reset/request", response_model=PasswordResetRequestOut)
async def request_password_reset(
    data: PasswordResetRequestIn, session: SessionDep
) -> PasswordResetRequestOut:
    try:
        token = await service.request_password_reset(session, data)
    except MailDeliveryError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "重置邮件暂时无法发送") from exc
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
    if "primary_model_id" in data.model_fields_set and data.primary_model_id is not None:
        model = await session.get(ModelCatalog, data.primary_model_id)
        if model is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "模型不在目录中")
        if "text-gen" not in (model.capabilities or []):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "只能选择推理模型")
    try:
        return await service.update_org(
            session,
            user_id,
            org_id,
            data.name,
            data.description,
            data.primary_model_id,
            update_primary_model="primary_model_id" in data.model_fields_set,
        )
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


@router.patch("/orgs/{org_id}/members/{member_user_id}", response_model=MemberOut)
async def update_member_role(
    org_id: uuid.UUID,
    member_user_id: uuid.UUID,
    data: MemberRoleUpdateIn,
    user_id: CurrentUserId,
    session: SessionDep,
) -> MemberOut:
    try:
        return await service.update_member_role(session, user_id, org_id, member_user_id, data)
    except service.NotOwner as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "需所有者权限") from exc
    except service.MemberNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "成员不存在") from exc
    except service.CannotRemoveLastOwner as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "不能降级最后一个所有者") from exc


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


@router.patch("/orgs/current/agents/{agent_id}/model", response_model=AgentOut)
async def update_current_org_agent_model(
    agent_id: uuid.UUID,
    data: AgentModelUpdateIn,
    org: OwnerOrg,
    user_id: CurrentUserId,
    session: SessionDep,
) -> dict[str, Any]:
    """owner 更新当前公司某 Agent 的模型选择；null 表示回退系统默认模型。"""
    if data.model_id is not None:
        model = await session.get(ModelCatalog, data.model_id)
        if model is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "模型不在目录中")
        if "text-gen" not in (model.capabilities or []):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "只能选择推理模型")

    updated = await repo.update_agent_model(session, agent_id, data.model_id)
    if updated is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent 不存在")
    await write_audit(
        session,
        action="agent.model.update",
        actor=str(user_id),
        org_id=org.org_id,
        target=str(agent_id),
        detail={"model_id": data.model_id},
    )
    return updated


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
