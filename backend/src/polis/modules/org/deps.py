"""org 模块 API 依赖：当前用户（access JWT）、当前公司（X-Org-Id + RLS 上下文）、权限守卫。"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import Cookie, Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from polis.core.security import decode_token
from polis.db.session import get_session
from polis.modules.org import repository as repo

_bearer = HTTPBearer(auto_error=False)


def get_current_user_id(
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    access_cookie: Annotated[str | None, Cookie(alias="polis_access")] = None,
) -> uuid.UUID:
    token = creds.credentials if creds is not None else access_cookie
    if token is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "缺少访问令牌")
    try:
        payload = decode_token(token)
    except Exception as exc:  # noqa: BLE001 - 任何解码失败都视为未授权
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "令牌无效或已过期") from exc
    if payload.get("type") != "access":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "令牌类型错误")
    return uuid.UUID(payload["sub"])


CurrentUserId = Annotated[uuid.UUID, Depends(get_current_user_id)]


@dataclass
class OrgContext:
    org_id: uuid.UUID
    role: str


async def get_org_context(
    user_id: CurrentUserId,
    session: Annotated[AsyncSession, Depends(get_session)],
    x_org_id: Annotated[uuid.UUID | None, Header(alias="X-Org-Id")] = None,
) -> OrgContext:
    """校验当前用户是该公司成员，并把会话切到受 RLS 的角色 + 设当前公司（本请求事务内）。"""
    if x_org_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "缺少 X-Org-Id 头")
    member = await repo.get_member(session, x_org_id, user_id)
    if member is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "你不属于该公司")
    await session.execute(text("SET LOCAL ROLE polis_app"))
    await session.execute(
        text("SELECT set_config('app.current_org', :o, true)"), {"o": str(x_org_id)}
    )
    return OrgContext(org_id=x_org_id, role=member.role)


CurrentOrg = Annotated[OrgContext, Depends(get_org_context)]


def require_role(*allowed: str) -> Callable[[OrgContext], Awaitable[OrgContext]]:
    """路由守卫：要求当前用户在该公司的角色属于 allowed（owner/approver/member）。"""

    async def dep(ctx: CurrentOrg) -> OrgContext:
        if ctx.role not in allowed:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "权限不足")
        return ctx

    return dep
