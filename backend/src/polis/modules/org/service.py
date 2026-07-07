"""org/身份 业务逻辑。service 不依赖 web，错误以领域异常抛出，由 api 层翻译为 HTTP。"""

from __future__ import annotations

import logging
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from polis.config import get_settings
from polis.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    hash_token,
    verify_password,
)
from polis.modules.observability.audit import write_audit
from polis.modules.org import repository as repo
from polis.modules.org.schemas import (
    InviteCreateIn,
    InviteOut,
    LoginIn,
    MemberOut,
    MemberRoleUpdateIn,
    MeOut,
    OrgCreateIn,
    OrgOut,
    PasswordResetConfirmIn,
    PasswordResetRequestIn,
    RegisterIn,
    TokenOut,
    UserOut,
)

logger = logging.getLogger(__name__)


class AuthError(Exception):
    """认证/授权领域错误基类。"""


class EmailExists(AuthError):
    pass


class InvalidCredentials(AuthError):
    pass


class InvalidToken(AuthError):
    pass


class InvalidPasswordResetToken(AuthError):
    pass


class NotOwner(AuthError):
    """需要所有者权限（T9.3 权限矩阵）。"""


class InvalidInvite(AuthError):
    pass


class InviteEmailMismatch(AuthError):
    pass


class MemberNotFound(AuthError):
    pass


class CannotRemoveLastOwner(AuthError):
    pass


async def _issue_tokens(session: AsyncSession, user_id: uuid.UUID) -> TokenOut:
    access = create_access_token(user_id)
    refresh, expires_at = create_refresh_token(user_id)
    await repo.create_auth_session(session, user_id, hash_token(refresh), expires_at)
    return TokenOut(access_token=access, refresh_token=refresh)


async def register(session: AsyncSession, data: RegisterIn) -> TokenOut:
    if await repo.get_user_by_email(session, data.email):
        raise EmailExists(data.email)
    user = await repo.create_user(
        session, data.email, hash_password(data.password), data.display_name
    )
    tokens = await _issue_tokens(session, user.id)
    await write_audit(session, action="auth.register", actor=str(user.id), target=str(user.id))
    await session.flush()
    return tokens


async def login(session: AsyncSession, data: LoginIn) -> TokenOut:
    user = await repo.get_user_by_email(session, data.email)
    if user is None or user.password_hash is None:
        raise InvalidCredentials()
    if not verify_password(user.password_hash, data.password):
        raise InvalidCredentials()
    tokens = await _issue_tokens(session, user.id)
    await write_audit(session, action="auth.login", actor=str(user.id))
    await session.flush()
    return tokens


async def refresh(session: AsyncSession, refresh_token: str) -> TokenOut:
    try:
        payload = decode_token(refresh_token)
    except Exception as exc:  # noqa: BLE001 - 任何解码失败都视为无效令牌
        raise InvalidToken() from exc
    if payload.get("type") != "refresh":
        raise InvalidToken()
    row = await repo.get_active_session_by_hash(session, hash_token(refresh_token))
    if row is None:
        raise InvalidToken()
    user_id = uuid.UUID(payload["sub"])
    # 轮换：吊销旧会话，发放全新 access+refresh（旧 refresh 复用即失效，TD-012）
    await repo.revoke_session_by_hash(session, hash_token(refresh_token))
    tokens = await _issue_tokens(session, user_id)
    await write_audit(session, action="auth.refresh", actor=str(user_id))
    await session.flush()
    return tokens


async def logout(session: AsyncSession, refresh_token: str) -> None:
    """吊销 refresh 会话（幂等：无效/已吊销 token 也返回成功，不泄露存在性）。"""
    revoked = await repo.revoke_session_by_hash(session, hash_token(refresh_token))
    if revoked:
        try:
            payload = decode_token(refresh_token)
            await write_audit(session, action="auth.logout", actor=str(payload.get("sub")))
        except Exception:  # noqa: BLE001 - 审计 actor 取不到不阻断登出
            logger.debug("登出审计 actor 解析失败，跳过审计")
    await session.flush()


async def request_password_reset(session: AsyncSession, data: PasswordResetRequestIn) -> str | None:
    """创建一次性重置令牌；不存在的邮箱也返回 None，避免账号枚举。"""
    user = await repo.get_user_by_email(session, data.email)
    if user is None or user.password_hash is None or user.status != "active":
        return None
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(UTC) + timedelta(minutes=get_settings().password_reset_ttl_minutes)
    await repo.create_password_reset_token(session, user.id, hash_token(token), expires_at)
    await write_audit(session, action="auth.password_reset.requested", actor=str(user.id))
    await session.flush()
    return token


async def confirm_password_reset(session: AsyncSession, data: PasswordResetConfirmIn) -> None:
    token_hash = hash_token(data.token)
    row = await repo.get_active_password_reset_token(session, token_hash)
    if row is None:
        raise InvalidPasswordResetToken()
    if not await repo.mark_password_reset_token_used(session, token_hash):
        raise InvalidPasswordResetToken()
    user = await repo.get_user_by_id(session, row.user_id)
    if user is None or user.status != "active":
        raise InvalidPasswordResetToken()
    user.password_hash = hash_password(data.new_password)
    await repo.revoke_sessions_for_user(session, user.id)
    await write_audit(session, action="auth.password_reset.confirmed", actor=str(user.id))
    await session.flush()


async def me(session: AsyncSession, user_id: uuid.UUID) -> MeOut:
    user = await repo.get_user_by_id(session, user_id)
    if user is None:
        raise InvalidToken()
    orgs = await repo.list_orgs_for_user(session, user_id)
    return MeOut(
        user=UserOut(id=user.id, email=user.email, display_name=user.display_name),
        orgs=[OrgOut(id=o.id, name=o.name, role=role, description=o.charter) for o, role in orgs],
    )


async def create_org(session: AsyncSession, user_id: uuid.UUID, data: OrgCreateIn) -> OrgOut:
    org = await repo.create_org_with_owner(session, data.name, data.charter, user_id)
    await session.flush()
    await write_audit(
        session,
        action="org.create",
        actor=str(user_id),
        org_id=org.id,
        target=str(org.id),
        detail={"name": org.name},
    )
    return OrgOut(id=org.id, name=org.name, role="owner", description=org.charter)


async def _require_owner(session: AsyncSession, user_id: uuid.UUID, org_id: uuid.UUID) -> str:
    member = await repo.get_member(session, org_id, user_id)
    if member is None or member.role != "owner":
        raise NotOwner
    return member.role


async def update_org(
    session: AsyncSession,
    user_id: uuid.UUID,
    org_id: uuid.UUID,
    name: str,
    description: str | None,
) -> OrgOut:
    role = await _require_owner(session, user_id, org_id)
    org = await repo.get_org_by_id(session, org_id)
    if org is None:
        raise NotOwner
    org.name = name
    org.charter = description
    await session.flush()
    await write_audit(
        session,
        action="org.update",
        actor=str(user_id),
        org_id=org_id,
        target=str(org_id),
        detail={"name": name},
    )
    return OrgOut(id=org.id, name=org.name, role=role, description=org.charter)


async def list_members(
    session: AsyncSession, user_id: uuid.UUID, org_id: uuid.UUID
) -> list[MemberOut]:
    if await repo.get_member(session, org_id, user_id) is None:
        raise NotOwner  # 非成员不可见（这里复用 NotOwner→403）
    rows = await repo.list_members(session, org_id)
    return [
        MemberOut(user_id=u.id, email=u.email, display_name=u.display_name, role=role)
        for u, role in rows
    ]


async def create_invite(
    session: AsyncSession, user_id: uuid.UUID, org_id: uuid.UUID, data: InviteCreateIn
) -> InviteOut:
    await _require_owner(session, user_id, org_id)
    if await repo.get_org_by_id(session, org_id) is None:
        raise NotOwner

    email = str(data.email)
    existing_user = await repo.get_user_by_email(session, email)
    if existing_user is not None:
        existing_member = await repo.get_member(session, org_id, existing_user.id)
        if existing_member is not None:
            return InviteOut(email=email, role=existing_member.role, status="accepted")

    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(UTC) + timedelta(days=get_settings().org_invite_ttl_days)
    invite = await repo.create_org_invite(
        session,
        org_id=org_id,
        email=email,
        role=data.role,
        token_hash=hash_token(token),
        invited_by=user_id,
        expires_at=expires_at,
    )
    await write_audit(
        session,
        action="org.invite.create",
        actor=str(user_id),
        org_id=org_id,
        target=str(invite.id),
        detail={"email": email, "role": data.role},
    )
    await session.flush()
    return InviteOut(
        id=invite.id, email=invite.email, role=invite.role, status=invite.status, invite_token=token
    )


async def accept_invite(session: AsyncSession, user_id: uuid.UUID, token: str) -> MemberOut:
    invite = await repo.get_active_invite_by_hash(session, hash_token(token))
    if invite is None:
        raise InvalidInvite
    user = await repo.get_user_by_id(session, user_id)
    if user is None:
        raise InvalidInvite
    if user.email.lower() != invite.email.lower():
        raise InviteEmailMismatch

    existing_member = await repo.get_member(session, invite.org_id, user_id)
    if existing_member is None:
        await repo.add_org_member(session, invite.org_id, user_id, invite.role)
        role = invite.role
    else:
        role = existing_member.role

    if not await repo.mark_org_invite_accepted(session, invite.id):
        raise InvalidInvite
    await write_audit(
        session,
        action="org.invite.accept",
        actor=str(user_id),
        org_id=invite.org_id,
        target=str(invite.id),
        detail={"email": invite.email, "role": role},
    )
    await session.flush()
    return MemberOut(user_id=user.id, email=user.email, display_name=user.display_name, role=role)


async def remove_member(
    session: AsyncSession, user_id: uuid.UUID, org_id: uuid.UUID, member_user_id: uuid.UUID
) -> None:
    await _require_owner(session, user_id, org_id)
    member = await repo.get_member(session, org_id, member_user_id)
    if member is None:
        raise MemberNotFound
    if member.role == "owner" and await repo.count_owners(session, org_id) <= 1:
        raise CannotRemoveLastOwner

    await repo.delete_org_member(session, org_id, member_user_id)
    await write_audit(
        session,
        action="org.member.remove",
        actor=str(user_id),
        org_id=org_id,
        target=str(member_user_id),
        detail={"role": member.role},
    )
    await session.flush()


async def update_member_role(
    session: AsyncSession,
    user_id: uuid.UUID,
    org_id: uuid.UUID,
    member_user_id: uuid.UUID,
    data: MemberRoleUpdateIn,
) -> MemberOut:
    await _require_owner(session, user_id, org_id)
    member = await repo.get_member(session, org_id, member_user_id)
    if member is None:
        raise MemberNotFound

    old_role = member.role
    if (
        old_role == "owner"
        and data.role != "owner"
        and await repo.count_owners(session, org_id) <= 1
    ):
        raise CannotRemoveLastOwner

    await repo.update_org_member_role(session, org_id, member_user_id, data.role)
    if data.role == "owner":
        await repo.set_org_owner_user_id(session, org_id, member_user_id)
    elif old_role == "owner":
        replacement_owner_id = await repo.get_any_owner_user_id(
            session, org_id, exclude_user_id=member_user_id
        )
        if replacement_owner_id is None:
            raise CannotRemoveLastOwner
        await repo.set_org_owner_user_id(session, org_id, replacement_owner_id)

    user = await repo.get_user_by_id(session, member_user_id)
    if user is None:
        raise MemberNotFound
    await write_audit(
        session,
        action="org.member.role_update",
        actor=str(user_id),
        org_id=org_id,
        target=str(member_user_id),
        detail={"from": old_role, "to": data.role},
    )
    await session.flush()
    return MemberOut(
        user_id=user.id, email=user.email, display_name=user.display_name, role=data.role
    )


async def delete_org(session: AsyncSession, user_id: uuid.UUID, org_id: uuid.UUID) -> None:
    await _require_owner(session, user_id, org_id)
    org = await repo.get_org_by_id(session, org_id)
    if org is None:
        raise NotOwner
    name = org.name
    await session.delete(org)  # 级联删除 role/agent/memory… (FK ON DELETE CASCADE)
    await session.flush()
    await write_audit(
        session,
        action="org.delete",
        actor=str(user_id),
        org_id=None,
        target=str(org_id),
        detail={"name": name},
    )
