"""org/身份 业务逻辑。service 不依赖 web，错误以领域异常抛出，由 api 层翻译为 HTTP。"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

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
    LoginIn,
    MeOut,
    OrgCreateIn,
    OrgOut,
    RegisterIn,
    TokenOut,
    UserOut,
)


class AuthError(Exception):
    """认证/授权领域错误基类。"""


class EmailExists(AuthError):
    pass


class InvalidCredentials(AuthError):
    pass


class InvalidToken(AuthError):
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
    await session.flush()
    return tokens


async def login(session: AsyncSession, data: LoginIn) -> TokenOut:
    user = await repo.get_user_by_email(session, data.email)
    if user is None or user.password_hash is None:
        raise InvalidCredentials()
    if not verify_password(user.password_hash, data.password):
        raise InvalidCredentials()
    tokens = await _issue_tokens(session, user.id)
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
    access = create_access_token(user_id)
    return TokenOut(access_token=access, refresh_token=refresh_token)


async def me(session: AsyncSession, user_id: uuid.UUID) -> MeOut:
    user = await repo.get_user_by_id(session, user_id)
    if user is None:
        raise InvalidToken()
    orgs = await repo.list_orgs_for_user(session, user_id)
    return MeOut(
        user=UserOut(id=user.id, email=user.email, display_name=user.display_name),
        orgs=[OrgOut(id=o.id, name=o.name, role=role) for o, role in orgs],
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
    return OrgOut(id=org.id, name=org.name, role="owner")
