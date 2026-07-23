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
    Computed,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    PrimaryKeyConstraint,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
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


class Scope(UUIDPkMixin, OrgScopedMixin, TimestampMixin, Base):
    __tablename__ = "scope"

    domain_package_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("domain_package_version.id", ondelete="RESTRICT")
    )
    scope_type: Mapped[str] = mapped_column(Text)
    parent_scope_id: Mapped[uuid.UUID | None]
    external_ref: Mapped[str | None] = mapped_column(Text)
    display_name: Mapped[str] = mapped_column(Text)
    attributes: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    status: Mapped[str] = mapped_column(Text, server_default="active")
    version: Mapped[int] = mapped_column(Integer, server_default="1")

    __table_args__ = (
        UniqueConstraint("org_id", "id", name="uq_scope_org_id_id"),
        ForeignKeyConstraint(
            ("org_id", "parent_scope_id"),
            ("scope.org_id", "scope.id"),
            ondelete="RESTRICT",
            name="fk_scope_org_parent",
        ),
        CheckConstraint("status IN ('active','archived')", name="status"),
        CheckConstraint("version >= 1", name="version"),
        Index("ix_scope_org_type_status", "org_id", "scope_type", "status"),
        Index("ix_scope_org_parent", "org_id", "parent_scope_id"),
        Index(
            "uq_scope_org_external_ref",
            "org_id",
            "external_ref",
            unique=True,
            postgresql_where=text("external_ref IS NOT NULL"),
        ),
        Index(
            "uq_scope_org_governance",
            "org_id",
            unique=True,
            postgresql_where=text("scope_type = 'org_governance'"),
        ),
    )


class ScopeRelation(UUIDPkMixin, OrgScopedMixin, Base):
    __tablename__ = "scope_relation"

    domain_package_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("domain_package_version.id", ondelete="RESTRICT")
    )
    relationship_type: Mapped[str] = mapped_column(Text)
    from_scope_id: Mapped[uuid.UUID]
    to_scope_id: Mapped[uuid.UUID]
    attributes: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    status: Mapped[str] = mapped_column(Text, server_default="active")
    version: Mapped[int] = mapped_column(Integer, server_default="1")
    created_by_kind: Mapped[str] = mapped_column(Text)
    created_by_ref: Mapped[uuid.UUID]
    active_key: Mapped[str | None] = mapped_column(
        Text,
        Computed(
            "CASE WHEN status = 'active' THEN "
            "relationship_type || ':' || from_scope_id::text || ':' || to_scope_id::text END",
            persisted=True,
        ),
    )
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        ForeignKeyConstraint(
            ("org_id", "from_scope_id"),
            ("scope.org_id", "scope.id"),
            ondelete="RESTRICT",
            name="fk_scope_relation_org_from",
        ),
        ForeignKeyConstraint(
            ("org_id", "to_scope_id"),
            ("scope.org_id", "scope.id"),
            ondelete="RESTRICT",
            name="fk_scope_relation_org_to",
        ),
        UniqueConstraint("org_id", "active_key", name="uq_scope_relation_org_active_key"),
        CheckConstraint("from_scope_id <> to_scope_id", name="distinct_ends"),
        CheckConstraint("status IN ('active','ended')", name="status"),
        CheckConstraint("version >= 1", name="version"),
        CheckConstraint("created_by_kind IN ('human','agent','service')", name="created_by_kind"),
        Index("ix_scope_relation_org_from", "org_id", "from_scope_id", "status"),
        Index("ix_scope_relation_org_to", "org_id", "to_scope_id", "status"),
    )


class ScopeRoleAssignment(UUIDPkMixin, OrgScopedMixin, TimestampMixin, Base):
    __tablename__ = "scope_role_assignment"

    scope_id: Mapped[uuid.UUID]
    role_definition_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("role_definition_version.id", ondelete="RESTRICT")
    )
    actor_kind: Mapped[str] = mapped_column(Text)
    actor_ref: Mapped[uuid.UUID]
    inheritance_mode: Mapped[str] = mapped_column(Text, server_default="none")
    authority_constraints: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb")
    )
    status: Mapped[str] = mapped_column(Text, server_default="pending")
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    assigned_by_kind: Mapped[str] = mapped_column(Text)
    assigned_by_ref: Mapped[uuid.UUID]
    version: Mapped[int] = mapped_column(Integer, server_default="1")

    __table_args__ = (
        UniqueConstraint("org_id", "id", name="uq_scope_role_assignment_org_id_id"),
        ForeignKeyConstraint(
            ("org_id", "scope_id"),
            ("scope.org_id", "scope.id"),
            ondelete="CASCADE",
            name="fk_scope_role_assignment_org_scope",
        ),
        CheckConstraint("actor_kind IN ('human','agent','service')", name="actor_kind"),
        CheckConstraint("assigned_by_kind IN ('human','agent','service')", name="assigned_by_kind"),
        CheckConstraint("inheritance_mode IN ('none','descendants')", name="inheritance_mode"),
        CheckConstraint("status IN ('pending','active','suspended','ended')", name="status"),
        CheckConstraint(
            "valid_until IS NULL OR valid_from IS NULL OR valid_until > valid_from",
            name="validity",
        ),
        CheckConstraint("version >= 1", name="version"),
        Index(
            "ix_scope_role_assignment_scope_role_status",
            "org_id",
            "scope_id",
            "role_definition_version_id",
            "status",
        ),
        Index(
            "ix_scope_role_assignment_actor_status",
            "org_id",
            "actor_kind",
            "actor_ref",
            "status",
        ),
    )


class WorkItem(UUIDPkMixin, OrgScopedMixin, TimestampMixin, Base):
    __tablename__ = "work_item"

    scope_id: Mapped[uuid.UUID]
    parent_work_item_id: Mapped[uuid.UUID | None]
    definition_bundle_id: Mapped[uuid.UUID]
    title: Mapped[str] = mapped_column(Text)
    lifecycle_state: Mapped[str] = mapped_column(Text)
    execution_status: Mapped[str] = mapped_column(Text, server_default="idle")
    inputs: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    priority: Mapped[int] = mapped_column(Integer, server_default="0")
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_kind: Mapped[str] = mapped_column(Text)
    created_by_ref: Mapped[uuid.UUID]
    version: Mapped[int] = mapped_column(Integer, server_default="1")
    input_revision: Mapped[int] = mapped_column(Integer, server_default="1")
    kernel_mode: Mapped[str] = mapped_column(Text, server_default="native")
    current_plan_id: Mapped[uuid.UUID | None]
    active_run_id: Mapped[uuid.UUID | None]
    latest_evaluation_id: Mapped[uuid.UUID | None]
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("org_id", "id", name="uq_work_item_org_id_id"),
        ForeignKeyConstraint(
            ("org_id", "scope_id"),
            ("scope.org_id", "scope.id"),
            ondelete="RESTRICT",
            name="fk_work_item_org_scope",
        ),
        ForeignKeyConstraint(
            ("org_id", "parent_work_item_id"),
            ("work_item.org_id", "work_item.id"),
            ondelete="RESTRICT",
            name="fk_work_item_org_parent",
        ),
        ForeignKeyConstraint(
            ("org_id", "definition_bundle_id"),
            ("definition_bundle.org_id", "definition_bundle.id"),
            ondelete="RESTRICT",
            name="fk_work_item_org_bundle",
        ),
        CheckConstraint(
            "execution_status IN "
            "('idle','queued','running','waiting','evaluating','succeeded','failed','cancelled')",
            name="execution_status",
        ),
        CheckConstraint("priority BETWEEN 0 AND 100", name="priority"),
        CheckConstraint("created_by_kind IN ('human','agent','service')", name="created_by_kind"),
        CheckConstraint("version >= 1", name="version"),
        CheckConstraint("input_revision >= 1", name="input_revision"),
        CheckConstraint("kernel_mode IN ('native','legacy_shadow')", name="kernel_mode"),
        CheckConstraint(
            "(execution_status IN ('queued','running','waiting','evaluating')) "
            "OR active_run_id IS NULL",
            name="active_run_status",
        ),
        Index("ix_work_item_scope_lifecycle", "org_id", "scope_id", "lifecycle_state"),
        Index(
            "ix_work_item_execution_priority",
            "org_id",
            "execution_status",
            text("priority DESC"),
            "created_at",
        ),
        Index("ix_work_item_parent", "org_id", "parent_work_item_id"),
        Index("ix_work_item_bundle", "org_id", "definition_bundle_id"),
    )


class WorkRoleBinding(UUIDPkMixin, OrgScopedMixin, TimestampMixin, Base):
    __tablename__ = "work_role_binding"

    work_item_id: Mapped[uuid.UUID]
    role_slot_key: Mapped[str] = mapped_column(Text)
    responsible_assignment_id: Mapped[uuid.UUID]
    responsibility_kind_snapshot: Mapped[str] = mapped_column(Text)
    executor_kind: Mapped[str | None] = mapped_column(Text)
    executor_ref: Mapped[uuid.UUID | None]
    delegated_by_binding_id: Mapped[uuid.UUID | None]
    status: Mapped[str] = mapped_column(Text, server_default="active")
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, server_default="1")

    __table_args__ = (
        UniqueConstraint("org_id", "id", name="uq_work_role_binding_org_id_id"),
        ForeignKeyConstraint(
            ("org_id", "work_item_id"),
            ("work_item.org_id", "work_item.id"),
            ondelete="CASCADE",
            name="fk_work_role_binding_org_work",
        ),
        ForeignKeyConstraint(
            ("org_id", "responsible_assignment_id"),
            ("scope_role_assignment.org_id", "scope_role_assignment.id"),
            ondelete="RESTRICT",
            name="fk_work_role_binding_org_assignment",
        ),
        ForeignKeyConstraint(
            ("org_id", "delegated_by_binding_id"),
            ("work_role_binding.org_id", "work_role_binding.id"),
            ondelete="RESTRICT",
            name="fk_work_role_binding_org_delegated_by",
        ),
        CheckConstraint(
            "responsibility_kind_snapshot IN ('accountable','contributor','reviewer','observer')",
            name="responsibility_kind",
        ),
        CheckConstraint("(executor_kind IS NULL) = (executor_ref IS NULL)", name="executor_pair"),
        CheckConstraint(
            "executor_kind IS NULL OR executor_kind IN ('human','agent','service')",
            name="executor_kind",
        ),
        CheckConstraint("status IN ('active','revoked','ended')", name="status"),
        CheckConstraint(
            "valid_until IS NULL OR valid_from IS NULL OR valid_until > valid_from",
            name="validity",
        ),
        CheckConstraint("version >= 1", name="version"),
        Index(
            "uq_work_role_binding_active",
            "org_id",
            "work_item_id",
            "role_slot_key",
            "responsible_assignment_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
    )


class ServiceIdentity(UUIDPkMixin, OrgScopedMixin, Base):
    __tablename__ = "service_identity"

    key: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default="active")
    allowed_command_families: Mapped[list[str]] = mapped_column(
        ARRAY(Text), server_default=text("'{}'::text[]")
    )
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))

    __table_args__ = (
        UniqueConstraint("org_id", "key", name="uq_service_identity_org_key"),
        CheckConstraint("status IN ('active','disabled')", name="status"),
        CheckConstraint(
            "allowed_command_families <@ ARRAY['definition','scope','work']::text[]",
            name="allowed_command_families",
        ),
    )


class OrgKernelSetting(Base):
    __tablename__ = "org_kernel_setting"

    org_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("org.id", ondelete="CASCADE"), primary_key=True
    )
    kernel_mode: Mapped[str] = mapped_column(Text, server_default="legacy")
    governance_state: Mapped[str] = mapped_column(Text, server_default="uninitialized")
    governance_scope_id: Mapped[uuid.UUID | None]
    config_version: Mapped[int] = mapped_column(Integer, server_default="1")
    changed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id"))
    changed_at: Mapped[datetime] = mapped_column(server_default=text("now()"))

    __table_args__ = (
        ForeignKeyConstraint(
            ("org_id", "governance_scope_id"),
            ("scope.org_id", "scope.id"),
            ondelete="RESTRICT",
            name="fk_org_kernel_setting_org_governance_scope",
        ),
        CheckConstraint("kernel_mode IN ('legacy','shadow','kernel')", name="kernel_mode"),
        CheckConstraint("governance_state IN ('uninitialized','active')", name="governance_state"),
        CheckConstraint(
            "(governance_state = 'uninitialized' AND governance_scope_id IS NULL) OR "
            "(governance_state = 'active' AND governance_scope_id IS NOT NULL)",
            name="governance_pointer_state",
        ),
        CheckConstraint("config_version >= 1", name="config_version"),
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

    kind: Mapped[str | None] = mapped_column(Text)
    ref_id: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(Text, server_default="pending")
    assignee: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id"))
    decided_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id"))
    decided_at: Mapped[datetime | None]
    approval_schema_version: Mapped[int] = mapped_column(Integer, server_default="1")
    command_family: Mapped[str | None] = mapped_column(Text)
    domain_package_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("domain_package_version.id", ondelete="RESTRICT")
    )
    work_definition_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("work_definition_version.id", ondelete="RESTRICT")
    )
    role_definition_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("role_definition_version.id", ondelete="RESTRICT")
    )
    scope_id: Mapped[uuid.UUID | None]
    work_item_id: Mapped[uuid.UUID | None]
    command_type: Mapped[str | None] = mapped_column(Text)
    command_fingerprint: Mapped[str | None] = mapped_column(Text)
    approval_purpose: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int | None]
    requested_by_kind: Mapped[str | None] = mapped_column(Text)
    requested_by_ref: Mapped[uuid.UUID | None]
    required_role_slots: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_reason: Mapped[str | None] = mapped_column(Text)
    decided_by_kind: Mapped[str | None] = mapped_column(Text)
    decided_by_ref: Mapped[uuid.UUID | None]
    consumed_by_command_id: Mapped[uuid.UUID | None]
    command_receipt_id: Mapped[uuid.UUID | None]
    resume_mode: Mapped[str | None] = mapped_column(Text)
    payload_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    __table_args__ = (
        UniqueConstraint("org_id", "id", name="uq_approval_org_id_id"),
        CheckConstraint(
            "(approval_schema_version = 1 AND kind IN "
            "('plan','dangerous_action','provision_review','skill_review','rework')) OR "
            "(approval_schema_version = 2 AND kind IS NULL)",
            name="kind",
        ),
        CheckConstraint(
            "(approval_schema_version = 1 AND status IN "
            "('pending','approved','rejected')) OR "
            "(approval_schema_version = 2 AND status IN "
            "('pending','approved','rejected','expired','revoked','consumed'))",
            name="status",
        ),
        CheckConstraint("approval_schema_version IN (1,2)", name="schema_version"),
        CheckConstraint(
            "approval_schema_version = 1 OR ("
            "command_family IS NOT NULL AND "
            "command_family IN ('definition','scope','work') AND "
            "command_type IS NOT NULL AND "
            "command_fingerprint IS NOT NULL AND "
            "command_fingerprint ~ '^[0-9a-f]{64}$' AND "
            "approval_purpose IS NOT NULL AND "
            "approval_purpose IN ('command_policy','execution_gate','quality_review') AND "
            "version IS NOT NULL AND version >= 1 AND "
            "requested_by_kind IS NOT NULL AND "
            "requested_by_kind IN ('human','agent','service') AND "
            "requested_by_ref IS NOT NULL AND required_role_slots IS NOT NULL AND "
            "cardinality(required_role_slots) >= 1 AND "
            "expires_at IS NOT NULL AND command_receipt_id IS NOT NULL AND "
            "resume_mode IS NOT NULL AND resume_mode IN ('manual','automatic') AND "
            "payload_snapshot IS NOT NULL AND "
            "((command_family = 'definition' AND scope_id IS NULL AND work_item_id IS NULL "
            "AND num_nonnulls(domain_package_version_id,work_definition_version_id,"
            "role_definition_version_id) = 1) OR "
            "(command_family = 'scope' AND scope_id IS NOT NULL AND work_item_id IS NULL "
            "AND num_nonnulls(domain_package_version_id,work_definition_version_id,"
            "role_definition_version_id) = 0) OR "
            "(command_family = 'work' AND work_item_id IS NOT NULL AND scope_id IS NULL "
            "AND num_nonnulls(domain_package_version_id,work_definition_version_id,"
            "role_definition_version_id) = 0)))",
            name="v2_contract",
        ),
        CheckConstraint(
            "approval_schema_version = 1 OR ("
            "(status = 'pending' AND decided_by_kind IS NULL AND decided_by_ref IS NULL "
            "AND decided_at IS NULL AND consumed_by_command_id IS NULL) OR "
            "(status IN ('approved','rejected','expired','revoked') "
            "AND decided_by_kind IS NOT NULL AND decided_by_ref IS NOT NULL "
            "AND decided_at IS NOT NULL AND consumed_by_command_id IS NULL) OR "
            "(status = 'consumed' AND decided_by_kind IS NOT NULL "
            "AND decided_by_ref IS NOT NULL AND decided_at IS NOT NULL "
            "AND consumed_by_command_id IS NOT NULL))",
            name="v2_state",
        ),
        CheckConstraint(
            "(decided_by_kind IS NULL) = (decided_by_ref IS NULL)",
            name="decided_actor_pair",
        ),
        ForeignKeyConstraint(
            ("org_id", "scope_id"),
            ("scope.org_id", "scope.id"),
            ondelete="RESTRICT",
            name="fk_approval_org_scope",
        ),
        ForeignKeyConstraint(
            ("org_id", "work_item_id"),
            ("work_item.org_id", "work_item.id"),
            ondelete="RESTRICT",
            name="fk_approval_org_work",
        ),
        Index(
            "ix_approval_org_family_status_expires",
            "org_id",
            "command_family",
            "status",
            "expires_at",
        ),
        Index(
            "uq_approval_v2_org_receipt",
            "org_id",
            "command_receipt_id",
            unique=True,
            postgresql_where=text("approval_schema_version = 2"),
        ),
        Index(
            "uq_approval_v2_org_consumed_command",
            "org_id",
            "consumed_by_command_id",
            unique=True,
            postgresql_where=text("consumed_by_command_id IS NOT NULL"),
        ),
    )


class ApprovalDecision(UUIDPkMixin, OrgScopedMixin, Base):
    __tablename__ = "approval_decision"

    approval_id: Mapped[uuid.UUID]
    approval_version: Mapped[int]
    family_command_id: Mapped[uuid.UUID]
    requested_action: Mapped[str] = mapped_column(Text)
    outcome_status: Mapped[str] = mapped_column(Text)
    decided_by_kind: Mapped[str] = mapped_column(Text)
    decided_by_ref: Mapped[uuid.UUID]
    reason_code: Mapped[str | None] = mapped_column(Text)
    reason_note: Mapped[str | None] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ("org_id", "approval_id"),
            ("approval.org_id", "approval.id"),
            ondelete="CASCADE",
            name="fk_approval_decision_org_approval",
        ),
        UniqueConstraint(
            "org_id",
            "approval_id",
            "approval_version",
            name="uq_approval_decision_org_approval_version",
        ),
        UniqueConstraint(
            "org_id",
            "family_command_id",
            name="uq_approval_decision_org_family_command",
        ),
        CheckConstraint("approval_version >= 2", name="approval_version"),
        CheckConstraint(
            "requested_action IN ('approve','reject','expire','revoke','consume')",
            name="requested_action",
        ),
        CheckConstraint(
            "outcome_status IN ('approved','rejected','expired','revoked','consumed')",
            name="outcome_status",
        ),
        CheckConstraint(
            "decided_by_kind IN ('human','agent','service')",
            name="decided_by_kind",
        ),
        Index("ix_approval_decision_org_approval", "org_id", "approval_id"),
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
    "ApprovalDecision",
    "ArtifactDescriptor",
    "DefinitionBundle",
    "DefinitionBundleDependency",
    "DefinitionBundleRole",
    "DefinitionVersionMixin",
    "DomainPackageVersion",
    "OrgKernelSetting",
    "Plan",
    "ResultEnvelope",
    "RoleDefinitionVersion",
    "RunManifest",
    "Scope",
    "ScopeRelation",
    "ScopeRoleAssignment",
    "ServiceIdentity",
    "TaskRun",
    "WorkItem",
    "WorkDefinitionVersion",
    "WorkRoleBinding",
]
