"""org 模块 ORM：身份(app_user/auth_session/org_invite) + 组织/角色/Agent + 预设。

设计：docs/design/02、09、0b。枚举用 TEXT+CHECK；软扩展用 JSONB。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Index,
    PrimaryKeyConstraint,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, CITEXT, INET, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from polis.db.base import Base
from polis.db.mixins import OrgScopedMixin, TimestampMixin, UUIDPkMixin

# ---- 身份（平台级，无 org_id）----


class AppUser(UUIDPkMixin, TimestampMixin, Base):
    __tablename__ = "app_user"

    email: Mapped[str] = mapped_column(CITEXT, unique=True)
    password_hash: Mapped[str | None] = mapped_column(Text)
    display_name: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default="active")
    last_login_at: Mapped[datetime | None]

    __table_args__ = (CheckConstraint("status IN ('active','disabled')", name="status"),)


class AuthSession(UUIDPkMixin, Base):
    __tablename__ = "auth_session"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("app_user.id", ondelete="CASCADE"), index=True
    )
    refresh_hash: Mapped[str] = mapped_column(Text)
    user_agent: Mapped[str | None] = mapped_column(Text)
    ip: Mapped[str | None] = mapped_column(INET)
    expires_at: Mapped[datetime]
    revoked_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))


# ---- 组织级 ----


class Org(UUIDPkMixin, TimestampMixin, Base):
    __tablename__ = "org"

    name: Mapped[str] = mapped_column(Text)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id"))
    charter: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default="active")
    budget_cents: Mapped[int] = mapped_column(BigInteger, server_default="0")
    shared_schema: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    policies: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))

    __table_args__ = (CheckConstraint("status IN ('active','archived')", name="status"),)


class OrgMember(Base):
    __tablename__ = "org_member"

    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("org.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id"))
    role: Mapped[str] = mapped_column(Text)

    __table_args__ = (
        PrimaryKeyConstraint("org_id", "user_id"),
        CheckConstraint("role IN ('owner','approver','member')", name="role"),
    )


class OrgInvite(UUIDPkMixin, Base):
    __tablename__ = "org_invite"

    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("org.id", ondelete="CASCADE"), index=True)
    email: Mapped[str] = mapped_column(CITEXT)
    role: Mapped[str] = mapped_column(Text)
    token_hash: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default="pending")
    invited_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id"))
    expires_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))

    __table_args__ = (
        CheckConstraint("role IN ('approver','member')", name="role"),
        CheckConstraint("status IN ('pending','accepted','revoked','expired')", name="status"),
    )


class Role(UUIDPkMixin, OrgScopedMixin, Base):
    __tablename__ = "role"

    name: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)


class Agent(UUIDPkMixin, OrgScopedMixin, TimestampMixin, Base):
    __tablename__ = "agent"

    role_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("role.id"))
    name: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default="draft")
    current_version: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint("org_id", "name", name="org_id_name"),
        CheckConstraint("source IN ('preset','generated','custom')", name="source"),
        CheckConstraint("status IN ('draft','active','suspended','archived')", name="status"),
    )


class AgentVersion(UUIDPkMixin, OrgScopedMixin, Base):
    __tablename__ = "agent_version"

    agent_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[str] = mapped_column(Text)
    config: Mapped[dict[str, Any]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(Text, server_default="draft")
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))

    __table_args__ = (
        UniqueConstraint("agent_id", "version", name="agent_id_version"),
        CheckConstraint("status IN ('draft','published','deprecated')", name="status"),
    )


class AgentCapability(OrgScopedMixin, Base):
    __tablename__ = "agent_capability"

    agent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agent.id", ondelete="CASCADE"))
    capability: Mapped[str] = mapped_column(Text)
    level: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (PrimaryKeyConstraint("agent_id", "capability"),)


class OrgEnabledSkill(Base):
    __tablename__ = "org_enabled_skill"

    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("org.id", ondelete="CASCADE"))
    skill_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("skill.id", ondelete="CASCADE"))
    enabled_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id"))
    enabled_at: Mapped[datetime] = mapped_column(server_default=text("now()"))

    __table_args__ = (PrimaryKeyConstraint("org_id", "skill_id"),)


# ---- 全局共享（无 org_id）----


class ScenarioPreset(UUIDPkMixin, Base):
    __tablename__ = "scenario_preset"

    name: Mapped[str] = mapped_column(Text)
    version: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    required_capabilities: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    config: Mapped[dict[str, Any]] = mapped_column(JSONB)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1024))

    __table_args__ = (
        UniqueConstraint("name", "version", name="name_version"),
        Index(
            "ix_scenario_preset_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )
