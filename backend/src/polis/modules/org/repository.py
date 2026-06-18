"""org/身份 数据访问层。集中 SQL，service 只调这里（12 C 分层）。"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from polis.modules.org.models import AppUser, AuthSession, Org, OrgMember


async def get_user_by_email(session: AsyncSession, email: str) -> AppUser | None:
    user: AppUser | None = await session.scalar(select(AppUser).where(AppUser.email == email))
    return user


async def get_user_by_id(session: AsyncSession, user_id: uuid.UUID) -> AppUser | None:
    return await session.get(AppUser, user_id)


async def create_user(
    session: AsyncSession, email: str, password_hash: str, display_name: str | None
) -> AppUser:
    user = AppUser(email=email, password_hash=password_hash, display_name=display_name)
    session.add(user)
    await session.flush()
    return user


async def create_auth_session(
    session: AsyncSession, user_id: uuid.UUID, refresh_hash: str, expires_at: datetime
) -> AuthSession:
    row = AuthSession(user_id=user_id, refresh_hash=refresh_hash, expires_at=expires_at)
    session.add(row)
    await session.flush()
    return row


async def get_active_session_by_hash(
    session: AsyncSession, refresh_hash: str
) -> AuthSession | None:
    row: AuthSession | None = await session.scalar(
        select(AuthSession).where(
            AuthSession.refresh_hash == refresh_hash,
            AuthSession.revoked_at.is_(None),
        )
    )
    return row


async def create_org_with_owner(
    session: AsyncSession, name: str, charter: str | None, owner_user_id: uuid.UUID
) -> Org:
    org = Org(name=name, charter=charter, owner_user_id=owner_user_id)
    session.add(org)
    await session.flush()
    session.add(OrgMember(org_id=org.id, user_id=owner_user_id, role="owner"))
    await session.flush()
    return org


async def list_orgs_for_user(session: AsyncSession, user_id: uuid.UUID) -> list[tuple[Org, str]]:
    rows = await session.execute(
        select(Org, OrgMember.role)
        .join(OrgMember, OrgMember.org_id == Org.id)
        .where(OrgMember.user_id == user_id)
        .order_by(Org.created_at)
    )
    return [(org, role) for org, role in rows.all()]
