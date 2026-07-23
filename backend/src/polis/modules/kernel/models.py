"""Kernel-owned core runtime ORM models.

K0 moves declaration ownership only.  Table names, columns, constraints and
relationships must remain identical to their legacy definitions.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    PrimaryKeyConstraint,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from polis.db.base import Base
from polis.db.mixins import OrgScopedMixin, TimestampMixin, UUIDPkMixin


class DefinitionVersionMixin(UUIDPkMixin, TimestampMixin):
    """Shared columns for the three explicitly separate Definition tables."""

    owner_org_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("org.id"))
    key: Mapped[str] = mapped_column(Text)
    version: Mapped[str] = mapped_column(Text)
    visibility: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default="draft")
    schema_version: Mapped[int] = mapped_column(Integer, server_default="1")
    revision: Mapped[int] = mapped_column(Integer, server_default="1")
    definition: Mapped[dict[str, Any]] = mapped_column(JSONB)
    checksum: Mapped[str] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id"))
    published_at: Mapped[datetime | None]


def _definition_table_args(table_name: str, definition_kind: str) -> tuple[object, ...]:
    return (
        CheckConstraint("visibility IN ('public','private')", name="visibility"),
        CheckConstraint("status IN ('draft','published','deprecated')", name="status"),
        CheckConstraint("schema_version = 1", name="schema_version"),
        CheckConstraint("revision >= 1", name="revision"),
        CheckConstraint(
            "(status = 'draft' AND published_at IS NULL) OR "
            "(status IN ('published','deprecated') AND published_at IS NOT NULL)",
            name="status_published_at",
        ),
        CheckConstraint(
            "(visibility = 'public' AND owner_org_id IS NULL) OR "
            "(visibility = 'private' AND owner_org_id IS NOT NULL)",
            name="visibility_owner",
        ),
        CheckConstraint(
            f"definition ->> 'definition_kind' = '{definition_kind}'",
            name="definition_kind",
        ),
        CheckConstraint(
            "checksum ~ '^[0-9a-f]{64}$'",
            name="checksum_format",
        ),
        Index(
            f"uq_{table_name}_public_key_version",
            "key",
            "version",
            unique=True,
            postgresql_where=text("owner_org_id IS NULL"),
        ),
        Index(
            f"uq_{table_name}_private_key_version",
            "owner_org_id",
            "key",
            "version",
            unique=True,
            postgresql_where=text("owner_org_id IS NOT NULL"),
        ),
        Index(f"ix_{table_name}_owner_status", "owner_org_id", "status"),
        Index(f"ix_{table_name}_checksum", "checksum"),
    )


class DomainPackageVersion(DefinitionVersionMixin, Base):
    __tablename__ = "domain_package_version"
    __table_args__ = _definition_table_args(__tablename__, "domain_package")


class WorkDefinitionVersion(DefinitionVersionMixin, Base):
    __tablename__ = "work_definition_version"
    __table_args__ = _definition_table_args(__tablename__, "work")


class RoleDefinitionVersion(DefinitionVersionMixin, Base):
    __tablename__ = "role_definition_version"
    __table_args__ = _definition_table_args(__tablename__, "role")


class DefinitionBundle(UUIDPkMixin, OrgScopedMixin, Base):
    __tablename__ = "definition_bundle"

    domain_package_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("domain_package_version.id", ondelete="RESTRICT")
    )
    work_definition_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("work_definition_version.id", ondelete="RESTRICT")
    )
    compiled_definition: Mapped[dict[str, Any]] = mapped_column(JSONB)
    checksum: Mapped[str] = mapped_column(Text)
    compiler_version: Mapped[str] = mapped_column(Text)
    kernel_contract_version: Mapped[str] = mapped_column(Text)
    min_kernel_version: Mapped[str] = mapped_column(Text)
    child_work_bundle_dependencies: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))

    __table_args__ = (
        UniqueConstraint("org_id", "checksum", name="uq_definition_bundle_org_checksum"),
        UniqueConstraint("org_id", "id", name="uq_definition_bundle_org_id_id"),
        CheckConstraint("checksum ~ '^[0-9a-f]{64}$'", name="checksum_format"),
        Index(
            "ix_definition_bundle_org_work_version",
            "org_id",
            "work_definition_version_id",
        ),
        Index(
            "ix_definition_bundle_org_domain_version",
            "org_id",
            "domain_package_version_id",
        ),
    )


class DefinitionBundleRole(Base):
    __tablename__ = "definition_bundle_role"

    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("org.id", ondelete="CASCADE"))
    bundle_id: Mapped[uuid.UUID]
    role_slot_key: Mapped[str] = mapped_column(Text)
    role_definition_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("role_definition_version.id", ondelete="RESTRICT")
    )

    __table_args__ = (
        PrimaryKeyConstraint("bundle_id", "role_slot_key"),
        ForeignKeyConstraint(
            ("org_id", "bundle_id"),
            ("definition_bundle.org_id", "definition_bundle.id"),
            ondelete="CASCADE",
            name="fk_definition_bundle_role_org_bundle",
        ),
        Index("ix_definition_bundle_role_org_id", "org_id"),
    )


class DefinitionBundleDependency(Base):
    __tablename__ = "definition_bundle_dependency"

    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("org.id", ondelete="CASCADE"))
    parent_bundle_id: Mapped[uuid.UUID]
    dependency_key: Mapped[str] = mapped_column(Text)
    trigger_key: Mapped[str | None] = mapped_column(Text)
    child_bundle_id: Mapped[uuid.UUID]
    child_bundle_checksum: Mapped[str] = mapped_column(Text)

    __table_args__ = (
        PrimaryKeyConstraint("org_id", "parent_bundle_id", "dependency_key"),
        ForeignKeyConstraint(
            ("org_id", "parent_bundle_id"),
            ("definition_bundle.org_id", "definition_bundle.id"),
            ondelete="CASCADE",
            name="fk_definition_bundle_dependency_parent_bundle",
        ),
        ForeignKeyConstraint(
            ("org_id", "child_bundle_id"),
            ("definition_bundle.org_id", "definition_bundle.id"),
            ondelete="RESTRICT",
            name="fk_definition_bundle_dependency_child_bundle",
        ),
        UniqueConstraint(
            "org_id",
            "parent_bundle_id",
            "trigger_key",
            name="uq_definition_bundle_dependency_parent_trigger",
        ),
        CheckConstraint("child_bundle_checksum ~ '^[0-9a-f]{64}$'", name="checksum_format"),
    )


class Plan(UUIDPkMixin, OrgScopedMixin, Base):
    __tablename__ = "plan"

    goal: Mapped[str | None] = mapped_column(Text)
    dag: Mapped[dict[str, Any]] = mapped_column(JSONB)
    version: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default="draft")
    estimated_cost_cents: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))

    __table_args__ = (
        CheckConstraint(
            "status IN ('draft','approved','running','done','failed','needs_review')",
            name="status",
        ),
    )


class TaskRun(UUIDPkMixin, OrgScopedMixin, TimestampMixin, Base):
    """Existing task execution anchor; K4 evolves it additively into ExecutionRun."""

    __tablename__ = "task_run"

    task_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("task.id"))
    plan_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("plan.id"))
    temporal_workflow_id: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default="pending")
    priority: Mapped[int] = mapped_column(Integer, server_default="0")
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','running','paused','done','failed','needs_review')",
            name="status",
        ),
    )


class RunManifest(OrgScopedMixin, Base):
    """Reproducible execution snapshot keyed by the existing task run id."""

    __tablename__ = "run_manifest"

    task_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("task_run.id", ondelete="CASCADE"), primary_key=True
    )
    started_at: Mapped[datetime | None]
    agents_used: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    skills_used: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    models_used: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    plan_version: Mapped[str | None] = mapped_column(Text)
    plan_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class Approval(UUIDPkMixin, OrgScopedMixin, Base):
    __tablename__ = "approval"

    kind: Mapped[str] = mapped_column(Text)
    ref_id: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(Text, server_default="pending")
    assignee: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id"))
    decided_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id"))
    decided_at: Mapped[datetime | None]

    __table_args__ = (
        CheckConstraint(
            "kind IN ('plan','dangerous_action','provision_review','skill_review','rework')",
            name="kind",
        ),
        CheckConstraint("status IN ('pending','approved','rejected')", name="status"),
    )


class ResultEnvelope(UUIDPkMixin, OrgScopedMixin, Base):
    __tablename__ = "result_envelope"

    task_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("task_run.id"))
    node_id: Mapped[str | None] = mapped_column(Text)
    agent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agent.id"))
    status: Mapped[str | None] = mapped_column(Text)
    artifacts: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    facts: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    summary: Mapped[str | None] = mapped_column(Text)
    content: Mapped[str | None] = mapped_column(Text)
    tokens: Mapped[int | None] = mapped_column(Integer)
    needs_human: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))


class ArtifactDescriptor(UUIDPkMixin, OrgScopedMixin, Base):
    __tablename__ = "artifact_descriptor"

    task_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("task_run.id"))
    node_id: Mapped[str | None] = mapped_column(Text)
    modality: Mapped[str | None] = mapped_column(Text)
    uri: Mapped[str | None] = mapped_column(Text)
    mime: Mapped[str | None] = mapped_column(Text)
    caption: Mapped[str | None] = mapped_column(Text)
    provenance: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    meta: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))


__all__ = [
    "Approval",
    "ArtifactDescriptor",
    "DefinitionBundle",
    "DefinitionBundleDependency",
    "DefinitionBundleRole",
    "DefinitionVersionMixin",
    "DomainPackageVersion",
    "Plan",
    "ResultEnvelope",
    "RoleDefinitionVersion",
    "RunManifest",
    "TaskRun",
    "WorkDefinitionVersion",
]
