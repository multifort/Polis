"""org/身份 数据访问层。集中 SQL，service 只调这里（12 C 分层）。"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import CursorResult, delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from polis.modules.org.models import (
    Agent,
    AppUser,
    AuthRateLimitBucket,
    AuthSession,
    Org,
    OrgInvite,
    OrgMember,
    PasswordResetToken,
    Role,
    ScenarioPreset,
)


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
    """未吊销且未过期的会话才算 active（TD-012：补 expires_at 校验）。"""
    row: AuthSession | None = await session.scalar(
        select(AuthSession).where(
            AuthSession.refresh_hash == refresh_hash,
            AuthSession.revoked_at.is_(None),
            AuthSession.expires_at > func.now(),
        )
    )
    return row


async def revoke_session_by_hash(session: AsyncSession, refresh_hash: str) -> bool:
    """吊销指定 refresh（logout / 轮换吊销旧）。返回是否命中一条未吊销会话。"""
    result = cast(
        "CursorResult[Any]",
        await session.execute(
            update(AuthSession)
            .where(AuthSession.refresh_hash == refresh_hash, AuthSession.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC))
        ),
    )
    await session.flush()
    return result.rowcount > 0


async def cleanup_auth_sessions(session: AsyncSession) -> int:
    """删除已过期或已吊销的会话行，防止 auth_session 膨胀（TD-012）。返回删除行数。"""
    result = cast(
        "CursorResult[Any]",
        await session.execute(
            delete(AuthSession).where(
                or_(AuthSession.expires_at <= func.now(), AuthSession.revoked_at.is_not(None))
            )
        ),
    )
    await session.flush()
    return result.rowcount


async def create_password_reset_token(
    session: AsyncSession, user_id: uuid.UUID, token_hash: str, expires_at: datetime
) -> PasswordResetToken:
    row = PasswordResetToken(user_id=user_id, token_hash=token_hash, expires_at=expires_at)
    session.add(row)
    await session.flush()
    return row


async def get_active_password_reset_token(
    session: AsyncSession, token_hash: str
) -> PasswordResetToken | None:
    row: PasswordResetToken | None = await session.scalar(
        select(PasswordResetToken).where(
            PasswordResetToken.token_hash == token_hash,
            PasswordResetToken.used_at.is_(None),
            PasswordResetToken.expires_at > func.now(),
        )
    )
    return row


async def mark_password_reset_token_used(session: AsyncSession, token_hash: str) -> bool:
    result = cast(
        "CursorResult[Any]",
        await session.execute(
            update(PasswordResetToken)
            .where(
                PasswordResetToken.token_hash == token_hash,
                PasswordResetToken.used_at.is_(None),
            )
            .values(used_at=datetime.now(UTC))
        ),
    )
    await session.flush()
    return result.rowcount > 0


async def get_rate_limit_bucket_for_update(
    session: AsyncSession, key: str
) -> AuthRateLimitBucket | None:
    row: AuthRateLimitBucket | None = await session.scalar(
        select(AuthRateLimitBucket).where(AuthRateLimitBucket.key == key).with_for_update()
    )
    return row


async def get_or_create_rate_limit_bucket_for_update(
    session: AsyncSession, key: str
) -> AuthRateLimitBucket:
    await session.execute(
        pg_insert(AuthRateLimitBucket)
        .values(key=key, failures=[])
        .on_conflict_do_nothing(index_elements=[AuthRateLimitBucket.key])
    )
    row = await get_rate_limit_bucket_for_update(session, key)
    if row is None:  # pragma: no cover - defensive; insert/select should always produce a row.
        raise RuntimeError("auth rate limit bucket insert failed")
    return row


async def delete_rate_limit_bucket(session: AsyncSession, key: str) -> None:
    await session.execute(delete(AuthRateLimitBucket).where(AuthRateLimitBucket.key == key))
    await session.flush()


async def revoke_sessions_for_user(session: AsyncSession, user_id: uuid.UUID) -> int:
    result = cast(
        "CursorResult[Any]",
        await session.execute(
            update(AuthSession)
            .where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC))
        ),
    )
    await session.flush()
    return result.rowcount


async def create_org_with_owner(
    session: AsyncSession, name: str, charter: str | None, owner_user_id: uuid.UUID
) -> Org:
    org = Org(name=name, charter=charter, owner_user_id=owner_user_id)
    session.add(org)
    await session.flush()
    session.add(OrgMember(org_id=org.id, user_id=owner_user_id, role="owner"))
    await session.flush()
    return org


async def get_member(
    session: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID
) -> OrgMember | None:
    return await session.get(OrgMember, {"org_id": org_id, "user_id": user_id})


async def get_org_by_id(session: AsyncSession, org_id: uuid.UUID) -> Org | None:
    return await session.get(Org, org_id)


async def list_members(session: AsyncSession, org_id: uuid.UUID) -> list[tuple[AppUser, str]]:
    rows = await session.execute(
        select(AppUser, OrgMember.role)
        .join(OrgMember, OrgMember.user_id == AppUser.id)
        .where(OrgMember.org_id == org_id)
        .order_by(OrgMember.role, AppUser.email)
    )
    return [(u, role) for u, role in rows.all()]


async def count_owners(session: AsyncSession, org_id: uuid.UUID) -> int:
    count = await session.scalar(
        select(func.count())
        .select_from(OrgMember)
        .where(OrgMember.org_id == org_id, OrgMember.role == "owner")
    )
    return int(count or 0)


async def get_any_owner_user_id(
    session: AsyncSession, org_id: uuid.UUID, exclude_user_id: uuid.UUID | None = None
) -> uuid.UUID | None:
    stmt = select(OrgMember.user_id).where(OrgMember.org_id == org_id, OrgMember.role == "owner")
    if exclude_user_id is not None:
        stmt = stmt.where(OrgMember.user_id != exclude_user_id)
    owner_id: uuid.UUID | None = await session.scalar(stmt.order_by(OrgMember.user_id).limit(1))
    return owner_id


async def set_org_owner_user_id(
    session: AsyncSession, org_id: uuid.UUID, owner_user_id: uuid.UUID
) -> None:
    org = await session.get(Org, org_id)
    if org is not None:
        org.owner_user_id = owner_user_id
        await session.flush()


async def add_org_member(
    session: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, role: str
) -> OrgMember:
    member = OrgMember(org_id=org_id, user_id=user_id, role=role)
    session.add(member)
    await session.flush()
    return member


async def update_org_member_role(
    session: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, role: str
) -> OrgMember | None:
    member = await get_member(session, org_id, user_id)
    if member is None:
        return None
    member.role = role
    await session.flush()
    return member


async def delete_org_member(session: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    result = cast(
        "CursorResult[Any]",
        await session.execute(
            delete(OrgMember).where(OrgMember.org_id == org_id, OrgMember.user_id == user_id)
        ),
    )
    await session.flush()
    return result.rowcount > 0


async def create_org_invite(
    session: AsyncSession,
    org_id: uuid.UUID,
    email: str,
    role: str,
    token_hash: str,
    invited_by: uuid.UUID,
    expires_at: datetime,
) -> OrgInvite:
    invite = OrgInvite(
        org_id=org_id,
        email=email,
        role=role,
        token_hash=token_hash,
        invited_by=invited_by,
        expires_at=expires_at,
    )
    session.add(invite)
    await session.flush()
    return invite


async def get_active_invite_by_hash(session: AsyncSession, token_hash: str) -> OrgInvite | None:
    invite: OrgInvite | None = await session.scalar(
        select(OrgInvite).where(
            OrgInvite.token_hash == token_hash,
            OrgInvite.status == "pending",
            or_(OrgInvite.expires_at.is_(None), OrgInvite.expires_at > func.now()),
        )
    )
    return invite


async def mark_org_invite_accepted(session: AsyncSession, invite_id: uuid.UUID) -> bool:
    result = cast(
        "CursorResult[Any]",
        await session.execute(
            update(OrgInvite)
            .where(OrgInvite.id == invite_id, OrgInvite.status == "pending")
            .values(status="accepted")
        ),
    )
    await session.flush()
    return result.rowcount > 0


async def list_roles(session: AsyncSession) -> list[Role]:
    """当前公司的角色（RLS 已按 app.current_org 过滤）。"""
    return list((await session.scalars(select(Role).order_by(Role.name))).all())


async def list_agents(session: AsyncSession) -> list[Agent]:
    """当前公司的 Agent（RLS 过滤）。"""
    return list((await session.scalars(select(Agent).order_by(Agent.name))).all())


async def list_agents_detailed(session: AsyncSession) -> list[dict[str, Any]]:
    """当前公司 Agent + 角色名 + 版本配置（描述/能力/模型），供前端「Agent 详情」展示。

    描述取自 agent_version.config.prompt（promptSkeleton，说明该 Agent 职责）；
    能力/模型同取 config；角色名 join role（其 description 在预设实例化时可能为空）。
    """
    from polis.modules.org.models import AgentVersion

    rows = (
        await session.execute(
            select(Agent, Role.name, Role.description, AgentVersion.config)
            .outerjoin(Role, Agent.role_id == Role.id)
            .outerjoin(
                AgentVersion,
                (AgentVersion.agent_id == Agent.id)
                & (AgentVersion.version == Agent.current_version),
            )
            .order_by(Agent.name)
        )
    ).all()

    out: list[dict[str, Any]] = []
    for agent, role_name, role_desc, config in rows:
        cfg = config or {}
        out.append(
            {
                "id": agent.id,
                "name": agent.name,
                "status": agent.status,
                "source": agent.source,
                "current_version": agent.current_version,
                "role": role_name,
                "description": cfg.get("prompt") or role_desc,
                "capabilities": cfg.get("capabilities") or [],
                "model": cfg.get("model"),
            }
        )
    return out


async def update_agent_model(
    session: AsyncSession, agent_id: uuid.UUID, model_id: str | None
) -> dict[str, Any] | None:
    """更新当前公司某 Agent 当前版本的模型选择（RLS 已按 app.current_org 过滤）。"""
    from polis.modules.org.models import AgentVersion

    row = (
        await session.execute(
            select(Agent, Role.name, Role.description, AgentVersion)
            .outerjoin(Role, Agent.role_id == Role.id)
            .outerjoin(
                AgentVersion,
                (AgentVersion.agent_id == Agent.id)
                & (AgentVersion.version == Agent.current_version),
            )
            .where(Agent.id == agent_id)
        )
    ).first()
    if row is None:
        return None
    agent, role_name, role_desc, version = row
    if version is None:
        return None

    cfg = dict(version.config or {})
    if model_id is None:
        cfg.pop("model", None)
    else:
        cfg["model"] = model_id
    version.config = cfg
    await session.flush()

    return {
        "id": agent.id,
        "name": agent.name,
        "status": agent.status,
        "source": agent.source,
        "current_version": agent.current_version,
        "role": role_name,
        "description": cfg.get("prompt") or role_desc,
        "capabilities": cfg.get("capabilities") or [],
        "model": cfg.get("model"),
    }


async def get_preset_by_name(session: AsyncSession, name: str) -> ScenarioPreset | None:
    preset: ScenarioPreset | None = await session.scalar(
        select(ScenarioPreset)
        .where(ScenarioPreset.name == name)
        .order_by(ScenarioPreset.version.desc())
    )
    return preset


async def list_presets(session: AsyncSession) -> list[ScenarioPreset]:
    return list((await session.scalars(select(ScenarioPreset).order_by(ScenarioPreset.name))).all())


async def rank_presets_by_vector(
    session: AsyncSession, query_embedding: list[float], limit: int = 5
) -> list[tuple[ScenarioPreset, float]]:
    """按 query 向量与 preset.embedding 余弦相似排序（TD-017 语义选预设）。返回 (preset, 相似度)。

    仅含 embedding 非空的 preset（未回填的走关键词兜底）。相似度 = 1 - cosine_distance。
    """
    dist = ScenarioPreset.embedding.cosine_distance(query_embedding)
    rows = (
        await session.execute(
            select(ScenarioPreset, dist)
            .where(ScenarioPreset.embedding.isnot(None))
            .order_by(dist)
            .limit(limit)
        )
    ).all()
    return [(p, 1.0 - float(d)) for p, d in rows]


async def list_orgs_for_user(session: AsyncSession, user_id: uuid.UUID) -> list[tuple[Org, str]]:
    rows = await session.execute(
        select(Org, OrgMember.role)
        .join(OrgMember, OrgMember.org_id == Org.id)
        .where(OrgMember.user_id == user_id)
        .order_by(Org.created_at)
    )
    return [(org, role) for org, role in rows.all()]
