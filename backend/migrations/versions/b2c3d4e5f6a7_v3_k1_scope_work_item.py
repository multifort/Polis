"""V3 K1 Scope, responsibility, WorkItem and governance skeleton.

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-07-23
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

revision: str = "b2c3d4e5f6a7"
down_revision: str | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RLS_TABLES = (
    "scope",
    "scope_relation",
    "scope_role_assignment",
    "work_item",
    "work_role_binding",
    "service_identity",
    "org_kernel_setting",
)

GOVERNANCE_DOMAIN_ID = "00000000-0000-4000-8000-000000000301"
GOVERNANCE_ROLE_ID = "00000000-0000-4000-8000-000000000302"
GOVERNANCE_DOMAIN_CHECKSUM = "a18229c4029500e18937e3f7473ecca12ae16e03524d33c11db927a70732b4c2"
GOVERNANCE_ROLE_CHECKSUM = "1acaaf2b78043d90d80353e508b28d5ee9d4df40fbf8ddacbc5f0ef43c716ca6"
GOVERNANCE_DOMAIN = {
    "schema_version": 1,
    "definition_kind": "domain_package",
    "key": "kernel.governance",
    "display_name": "Polis Organization Governance",
    "scope_types": [
        {
            "key": "org_governance",
            "parent_types": [],
            "attributes_schema": {
                "type": "object",
                "required": ["kernel_policy"],
                "properties": {
                    "kernel_policy": {
                        "type": "object",
                        "required": ["schema_version"],
                        "properties": {"schema_version": {"type": "integer", "const": 1}},
                        "additionalProperties": True,
                    }
                },
                "additionalProperties": False,
            },
        }
    ],
    "relationship_types": [],
    "policy_defaults": {
        "unknown_action": "deny",
        "dangerous_action": "require_approval",
    },
    "compatible_work_definition_keys": [],
    "compatible_role_definition_keys": ["kernel.governance_owner"],
}
GOVERNANCE_ROLE = {
    "schema_version": 1,
    "definition_kind": "role",
    "key": "kernel.governance_owner",
    "display_name": "Organization Governance Owner",
    "mission": "Own the organization's Polis kernel governance configuration",
    "accountabilities": [
        "Maintain governance definitions and policy",
        "Authorize scope administration",
    ],
    "required_capabilities": [],
    "authority": {
        "commands": [
            "create_domain_package_definition",
            "update_domain_package_definition_draft",
            "publish_domain_package_definition",
            "deprecate_domain_package_definition",
            "create_work_definition",
            "update_work_definition_draft",
            "publish_work_definition",
            "deprecate_work_definition",
            "create_role_definition",
            "update_role_definition_draft",
            "publish_role_definition",
            "deprecate_role_definition",
            "compile_definition_bundle",
            "decide_definition_approval",
            "expire_definition_approval",
            "revoke_definition_approval",
            "create_scope",
            "update_scope",
            "archive_scope",
            "relate_scopes",
            "unrelate_scopes",
            "assign_scope_role",
            "activate_scope_role",
            "suspend_scope_role",
            "end_scope_role",
            "cancel_scope_schedule",
            "decide_scope_approval",
            "expire_scope_approval",
            "revoke_scope_approval",
        ],
        "tools": [],
        "data_scopes": [
            "kernel.definitions",
            "kernel.scopes",
            "kernel.governance",
        ],
        "max_risk_level": "critical",
        "budget_cents": 1000000000000000,
    },
    "collaboration": {"receives_from": [], "hands_off_to": [], "escalates_to": []},
    "quality_bar": {"evaluation_rule_keys": []},
    "capacity": {"max_active_work_items": 10000},
}


def _uuid_pk() -> sa.Column[object]:
    return sa.Column(
        "id",
        sa.Uuid(),
        server_default=sa.text("gen_random_uuid()"),
        nullable=False,
    )


def _org_id() -> sa.Column[object]:
    return sa.Column(
        "org_id",
        sa.Uuid(),
        sa.ForeignKey("org.id", ondelete="CASCADE"),
        nullable=False,
    )


def _timestamps() -> tuple[sa.Column[object], sa.Column[object]]:
    return (
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )


def upgrade() -> None:
    op.create_table(
        "scope",
        sa.Column(
            "domain_package_version_id",
            sa.Uuid(),
            sa.ForeignKey("domain_package_version.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("scope_type", sa.Text(), nullable=False),
        sa.Column("parent_scope_id", sa.Uuid(), nullable=True),
        sa.Column("external_ref", sa.Text(), nullable=True),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column(
            "attributes",
            JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("status", sa.Text(), server_default="active", nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        _uuid_pk(),
        _org_id(),
        *_timestamps(),
        sa.CheckConstraint("status IN ('active','archived')", name="ck_scope_status"),
        sa.CheckConstraint("version >= 1", name="ck_scope_version"),
        sa.ForeignKeyConstraint(
            ("org_id", "parent_scope_id"),
            ("scope.org_id", "scope.id"),
            ondelete="RESTRICT",
            name="fk_scope_org_parent",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_scope"),
        sa.UniqueConstraint("org_id", "id", name="uq_scope_org_id_id"),
    )
    op.create_index("ix_scope_org_id", "scope", ["org_id"])
    op.create_index("ix_scope_org_type_status", "scope", ["org_id", "scope_type", "status"])
    op.create_index("ix_scope_org_parent", "scope", ["org_id", "parent_scope_id"])
    op.create_index(
        "uq_scope_org_external_ref",
        "scope",
        ["org_id", "external_ref"],
        unique=True,
        postgresql_where=sa.text("external_ref IS NOT NULL"),
    )
    op.create_index(
        "uq_scope_org_governance",
        "scope",
        ["org_id"],
        unique=True,
        postgresql_where=sa.text("scope_type = 'org_governance'"),
    )

    op.create_table(
        "scope_relation",
        sa.Column(
            "domain_package_version_id",
            sa.Uuid(),
            sa.ForeignKey("domain_package_version.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("relationship_type", sa.Text(), nullable=False),
        sa.Column("from_scope_id", sa.Uuid(), nullable=False),
        sa.Column("to_scope_id", sa.Uuid(), nullable=False),
        sa.Column(
            "attributes",
            JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("status", sa.Text(), server_default="active", nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_by_kind", sa.Text(), nullable=False),
        sa.Column("created_by_ref", sa.Uuid(), nullable=False),
        sa.Column(
            "active_key",
            sa.Text(),
            sa.Computed(
                "CASE WHEN status = 'active' THEN relationship_type || ':' || "
                "from_scope_id::text || ':' || to_scope_id::text END",
                persisted=True,
            ),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        _uuid_pk(),
        _org_id(),
        sa.CheckConstraint("from_scope_id <> to_scope_id", name="ck_scope_relation_distinct_ends"),
        sa.CheckConstraint("status IN ('active','ended')", name="ck_scope_relation_status"),
        sa.CheckConstraint("version >= 1", name="ck_scope_relation_version"),
        sa.CheckConstraint(
            "created_by_kind IN ('human','agent','service')",
            name="ck_scope_relation_created_by_kind",
        ),
        sa.ForeignKeyConstraint(
            ("org_id", "from_scope_id"),
            ("scope.org_id", "scope.id"),
            ondelete="RESTRICT",
            name="fk_scope_relation_org_from",
        ),
        sa.ForeignKeyConstraint(
            ("org_id", "to_scope_id"),
            ("scope.org_id", "scope.id"),
            ondelete="RESTRICT",
            name="fk_scope_relation_org_to",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_scope_relation"),
        sa.UniqueConstraint("org_id", "active_key", name="uq_scope_relation_org_active_key"),
    )
    op.create_index("ix_scope_relation_org_id", "scope_relation", ["org_id"])
    op.create_index(
        "ix_scope_relation_org_from",
        "scope_relation",
        ["org_id", "from_scope_id", "status"],
    )
    op.create_index(
        "ix_scope_relation_org_to",
        "scope_relation",
        ["org_id", "to_scope_id", "status"],
    )

    op.create_table(
        "scope_role_assignment",
        sa.Column("scope_id", sa.Uuid(), nullable=False),
        sa.Column(
            "role_definition_version_id",
            sa.Uuid(),
            sa.ForeignKey("role_definition_version.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("actor_kind", sa.Text(), nullable=False),
        sa.Column("actor_ref", sa.Uuid(), nullable=False),
        sa.Column("inheritance_mode", sa.Text(), server_default="none", nullable=False),
        sa.Column(
            "authority_constraints",
            JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("status", sa.Text(), server_default="pending", nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("assigned_by_kind", sa.Text(), nullable=False),
        sa.Column("assigned_by_ref", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        _uuid_pk(),
        _org_id(),
        *_timestamps(),
        sa.CheckConstraint(
            "actor_kind IN ('human','agent','service')",
            name="ck_scope_role_assignment_actor_kind",
        ),
        sa.CheckConstraint(
            "assigned_by_kind IN ('human','agent','service')",
            name="ck_scope_role_assignment_assigned_by_kind",
        ),
        sa.CheckConstraint(
            "inheritance_mode IN ('none','descendants')",
            name="ck_scope_role_assignment_inheritance_mode",
        ),
        sa.CheckConstraint(
            "status IN ('pending','active','suspended','ended')",
            name="ck_scope_role_assignment_status",
        ),
        sa.CheckConstraint(
            "valid_until IS NULL OR valid_from IS NULL OR valid_until > valid_from",
            name="ck_scope_role_assignment_validity",
        ),
        sa.CheckConstraint("version >= 1", name="ck_scope_role_assignment_version"),
        sa.ForeignKeyConstraint(
            ("org_id", "scope_id"),
            ("scope.org_id", "scope.id"),
            ondelete="CASCADE",
            name="fk_scope_role_assignment_org_scope",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_scope_role_assignment"),
        sa.UniqueConstraint("org_id", "id", name="uq_scope_role_assignment_org_id_id"),
    )
    op.create_index("ix_scope_role_assignment_org_id", "scope_role_assignment", ["org_id"])
    op.create_index(
        "ix_scope_role_assignment_scope_role_status",
        "scope_role_assignment",
        ["org_id", "scope_id", "role_definition_version_id", "status"],
    )
    op.create_index(
        "ix_scope_role_assignment_actor_status",
        "scope_role_assignment",
        ["org_id", "actor_kind", "actor_ref", "status"],
    )

    op.create_table(
        "work_item",
        sa.Column("scope_id", sa.Uuid(), nullable=False),
        sa.Column("parent_work_item_id", sa.Uuid(), nullable=True),
        sa.Column("definition_bundle_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("lifecycle_state", sa.Text(), nullable=False),
        sa.Column("execution_status", sa.Text(), server_default="idle", nullable=False),
        sa.Column("inputs", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("priority", sa.Integer(), server_default="0", nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_kind", sa.Text(), nullable=False),
        sa.Column("created_by_ref", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("input_revision", sa.Integer(), server_default="1", nullable=False),
        sa.Column("kernel_mode", sa.Text(), server_default="native", nullable=False),
        sa.Column("current_plan_id", sa.Uuid(), nullable=True),
        sa.Column("active_run_id", sa.Uuid(), nullable=True),
        sa.Column("latest_evaluation_id", sa.Uuid(), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        _uuid_pk(),
        _org_id(),
        *_timestamps(),
        sa.CheckConstraint(
            "execution_status IN "
            "('idle','queued','running','waiting','evaluating','succeeded','failed','cancelled')",
            name="ck_work_item_execution_status",
        ),
        sa.CheckConstraint("priority BETWEEN 0 AND 100", name="ck_work_item_priority"),
        sa.CheckConstraint(
            "created_by_kind IN ('human','agent','service')",
            name="ck_work_item_created_by_kind",
        ),
        sa.CheckConstraint("version >= 1", name="ck_work_item_version"),
        sa.CheckConstraint("input_revision >= 1", name="ck_work_item_input_revision"),
        sa.CheckConstraint(
            "kernel_mode IN ('native','legacy_shadow')",
            name="ck_work_item_kernel_mode",
        ),
        sa.CheckConstraint(
            "(execution_status IN ('queued','running','waiting','evaluating')) "
            "OR active_run_id IS NULL",
            name="ck_work_item_active_run_status",
        ),
        sa.ForeignKeyConstraint(
            ("org_id", "scope_id"),
            ("scope.org_id", "scope.id"),
            ondelete="RESTRICT",
            name="fk_work_item_org_scope",
        ),
        sa.ForeignKeyConstraint(
            ("org_id", "parent_work_item_id"),
            ("work_item.org_id", "work_item.id"),
            ondelete="RESTRICT",
            name="fk_work_item_org_parent",
        ),
        sa.ForeignKeyConstraint(
            ("org_id", "definition_bundle_id"),
            ("definition_bundle.org_id", "definition_bundle.id"),
            ondelete="RESTRICT",
            name="fk_work_item_org_bundle",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_work_item"),
        sa.UniqueConstraint("org_id", "id", name="uq_work_item_org_id_id"),
    )
    op.create_index("ix_work_item_org_id", "work_item", ["org_id"])
    op.create_index(
        "ix_work_item_scope_lifecycle",
        "work_item",
        ["org_id", "scope_id", "lifecycle_state"],
    )
    op.create_index(
        "ix_work_item_execution_priority",
        "work_item",
        ["org_id", "execution_status", sa.text("priority DESC"), "created_at"],
    )
    op.create_index("ix_work_item_parent", "work_item", ["org_id", "parent_work_item_id"])
    op.create_index("ix_work_item_bundle", "work_item", ["org_id", "definition_bundle_id"])

    op.create_table(
        "work_role_binding",
        sa.Column("work_item_id", sa.Uuid(), nullable=False),
        sa.Column("role_slot_key", sa.Text(), nullable=False),
        sa.Column("responsible_assignment_id", sa.Uuid(), nullable=False),
        sa.Column("responsibility_kind_snapshot", sa.Text(), nullable=False),
        sa.Column("executor_kind", sa.Text(), nullable=True),
        sa.Column("executor_ref", sa.Uuid(), nullable=True),
        sa.Column("delegated_by_binding_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.Text(), server_default="active", nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        _uuid_pk(),
        _org_id(),
        *_timestamps(),
        sa.CheckConstraint(
            "responsibility_kind_snapshot IN ('accountable','contributor','reviewer','observer')",
            name="ck_work_role_binding_responsibility_kind",
        ),
        sa.CheckConstraint(
            "(executor_kind IS NULL) = (executor_ref IS NULL)",
            name="ck_work_role_binding_executor_pair",
        ),
        sa.CheckConstraint(
            "executor_kind IS NULL OR executor_kind IN ('human','agent','service')",
            name="ck_work_role_binding_executor_kind",
        ),
        sa.CheckConstraint(
            "status IN ('active','revoked','ended')",
            name="ck_work_role_binding_status",
        ),
        sa.CheckConstraint(
            "valid_until IS NULL OR valid_from IS NULL OR valid_until > valid_from",
            name="ck_work_role_binding_validity",
        ),
        sa.CheckConstraint("version >= 1", name="ck_work_role_binding_version"),
        sa.ForeignKeyConstraint(
            ("org_id", "work_item_id"),
            ("work_item.org_id", "work_item.id"),
            ondelete="CASCADE",
            name="fk_work_role_binding_org_work",
        ),
        sa.ForeignKeyConstraint(
            ("org_id", "responsible_assignment_id"),
            ("scope_role_assignment.org_id", "scope_role_assignment.id"),
            ondelete="RESTRICT",
            name="fk_work_role_binding_org_assignment",
        ),
        sa.ForeignKeyConstraint(
            ("org_id", "delegated_by_binding_id"),
            ("work_role_binding.org_id", "work_role_binding.id"),
            ondelete="RESTRICT",
            name="fk_work_role_binding_org_delegated_by",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_work_role_binding"),
        sa.UniqueConstraint("org_id", "id", name="uq_work_role_binding_org_id_id"),
    )
    op.create_index("ix_work_role_binding_org_id", "work_role_binding", ["org_id"])
    op.create_index(
        "uq_work_role_binding_active",
        "work_role_binding",
        ["org_id", "work_item_id", "role_slot_key", "responsible_assignment_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )

    op.create_table(
        "service_identity",
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default="active", nullable=False),
        sa.Column(
            "allowed_command_families",
            ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        _uuid_pk(),
        _org_id(),
        sa.CheckConstraint("status IN ('active','disabled')", name="ck_service_identity_status"),
        sa.CheckConstraint(
            "allowed_command_families <@ ARRAY['definition','scope','work']::text[]",
            name="ck_service_identity_allowed_command_families",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_service_identity"),
        sa.UniqueConstraint("org_id", "key", name="uq_service_identity_org_key"),
    )
    op.create_index("ix_service_identity_org_id", "service_identity", ["org_id"])

    op.create_table(
        "org_kernel_setting",
        sa.Column(
            "org_id",
            sa.Uuid(),
            sa.ForeignKey("org.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kernel_mode", sa.Text(), server_default="legacy", nullable=False),
        sa.Column(
            "governance_state",
            sa.Text(),
            server_default="uninitialized",
            nullable=False,
        ),
        sa.Column("governance_scope_id", sa.Uuid(), nullable=True),
        sa.Column("config_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "changed_by",
            sa.Uuid(),
            sa.ForeignKey("app_user.id"),
            nullable=True,
        ),
        sa.Column(
            "changed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "kernel_mode IN ('legacy','shadow','kernel')",
            name="ck_org_kernel_setting_kernel_mode",
        ),
        sa.CheckConstraint(
            "governance_state IN ('uninitialized','active')",
            name="ck_org_kernel_setting_governance_state",
        ),
        sa.CheckConstraint(
            "(governance_state = 'uninitialized' AND governance_scope_id IS NULL) OR "
            "(governance_state = 'active' AND governance_scope_id IS NOT NULL)",
            name="ck_org_kernel_setting_governance_pointer_state",
        ),
        sa.CheckConstraint("config_version >= 1", name="ck_org_kernel_setting_config_version"),
        sa.ForeignKeyConstraint(
            ("org_id", "governance_scope_id"),
            ("scope.org_id", "scope.id"),
            ondelete="RESTRICT",
            name="fk_org_kernel_setting_org_governance_scope",
        ),
        sa.PrimaryKeyConstraint("org_id", name="pk_org_kernel_setting"),
    )

    op.bulk_insert(
        sa.table(
            "domain_package_version",
            sa.column("id", sa.Uuid()),
            sa.column("owner_org_id", sa.Uuid()),
            sa.column("key", sa.Text()),
            sa.column("version", sa.Text()),
            sa.column("visibility", sa.Text()),
            sa.column("status", sa.Text()),
            sa.column("schema_version", sa.Integer()),
            sa.column("revision", sa.Integer()),
            sa.column("definition", JSONB()),
            sa.column("checksum", sa.Text()),
            sa.column("created_by", sa.Uuid()),
            sa.column("published_at", sa.DateTime(timezone=True)),
        ),
        [
            {
                "id": GOVERNANCE_DOMAIN_ID,
                "owner_org_id": None,
                "key": "kernel.governance",
                "version": "1.0.0",
                "visibility": "public",
                "status": "published",
                "schema_version": 1,
                "revision": 1,
                "definition": GOVERNANCE_DOMAIN,
                "checksum": GOVERNANCE_DOMAIN_CHECKSUM,
                "created_by": None,
                "published_at": datetime(2026, 7, 23, tzinfo=UTC),
            }
        ],
    )
    op.bulk_insert(
        sa.table(
            "role_definition_version",
            sa.column("id", sa.Uuid()),
            sa.column("owner_org_id", sa.Uuid()),
            sa.column("key", sa.Text()),
            sa.column("version", sa.Text()),
            sa.column("visibility", sa.Text()),
            sa.column("status", sa.Text()),
            sa.column("schema_version", sa.Integer()),
            sa.column("revision", sa.Integer()),
            sa.column("definition", JSONB()),
            sa.column("checksum", sa.Text()),
            sa.column("created_by", sa.Uuid()),
            sa.column("published_at", sa.DateTime(timezone=True)),
        ),
        [
            {
                "id": GOVERNANCE_ROLE_ID,
                "owner_org_id": None,
                "key": "kernel.governance_owner",
                "version": "1.0.0",
                "visibility": "public",
                "status": "published",
                "schema_version": 1,
                "revision": 1,
                "definition": GOVERNANCE_ROLE,
                "checksum": GOVERNANCE_ROLE_CHECKSUM,
                "created_by": None,
                "published_at": datetime(2026, 7, 23, tzinfo=UTC),
            }
        ],
    )

    op.execute(
        """
        CREATE FUNCTION kernel_validate_org_policy(value jsonb) RETURNS boolean
        LANGUAGE sql IMMUTABLE AS $$
          SELECT jsonb_typeof(value) = 'object'
            AND value ? 'kernel_policy'
            AND (SELECT array_agg(key ORDER BY key)
                 FROM jsonb_object_keys(value) key) = ARRAY['kernel_policy']
            AND jsonb_typeof(value->'kernel_policy') = 'object'
            AND (SELECT array_agg(key ORDER BY key)
                 FROM jsonb_object_keys(value->'kernel_policy') key) =
                ARRAY['budget_enforcement','budget_limit_cents',
                      'default_approval_ttl_seconds','max_concurrent_runs','schema_version']
            AND (value->'kernel_policy'->>'schema_version')::bigint = 1
            AND value->'kernel_policy'->>'schema_version' = '1'
            AND value->'kernel_policy'->>'max_concurrent_runs' ~ '^[0-9]+$'
            AND (value->'kernel_policy'->>'max_concurrent_runs')::bigint BETWEEN 1 AND 10000
            AND value->'kernel_policy'->>'budget_limit_cents' ~ '^[0-9]+$'
            AND (value->'kernel_policy'->>'budget_limit_cents')::numeric
                BETWEEN 0 AND 1000000000000000
            AND value->'kernel_policy'->>'budget_enforcement'
                IN ('observe','deny','require_approval')
            AND (value->'kernel_policy'->>'default_approval_ttl_seconds')::bigint
                BETWEEN 60 AND 604800
            AND value->'kernel_policy'->>'default_approval_ttl_seconds' ~ '^[0-9]+$'
            AND jsonb_typeof(value->'kernel_policy'->'schema_version') = 'number'
            AND jsonb_typeof(value->'kernel_policy'->'max_concurrent_runs') = 'number'
            AND jsonb_typeof(value->'kernel_policy'->'budget_limit_cents') = 'number'
            AND jsonb_typeof(value->'kernel_policy'->'budget_enforcement') = 'string'
            AND jsonb_typeof(value->'kernel_policy'->'default_approval_ttl_seconds') = 'number'
        $$
        """
    )
    op.execute(
        f"""
        CREATE FUNCTION kernel_guard_governance_scope() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_OP = 'DELETE' THEN
            IF OLD.scope_type = 'org_governance' THEN
              RAISE EXCEPTION 'governance scope is protected' USING ERRCODE = '55000';
            END IF;
            RETURN OLD;
          END IF;
          IF TG_OP = 'UPDATE' AND OLD.scope_type = 'org_governance'
             AND (NEW.scope_type IS DISTINCT FROM OLD.scope_type
               OR NEW.domain_package_version_id IS DISTINCT FROM OLD.domain_package_version_id
               OR NEW.parent_scope_id IS DISTINCT FROM OLD.parent_scope_id
               OR NEW.external_ref IS DISTINCT FROM OLD.external_ref
               OR NEW.display_name IS DISTINCT FROM OLD.display_name
               OR NEW.status IS DISTINCT FROM OLD.status) THEN
              RAISE EXCEPTION 'governance scope is protected' USING ERRCODE = '55000';
          END IF;
          IF NEW.scope_type = 'org_governance' THEN
            IF NEW.domain_package_version_id <> '{GOVERNANCE_DOMAIN_ID}'::uuid
               OR NEW.parent_scope_id IS NOT NULL
               OR NEW.external_ref IS NOT NULL
               OR NEW.display_name <> 'Organization Governance'
               OR NEW.status <> 'active'
               OR NOT kernel_validate_org_policy(NEW.attributes) THEN
              RAISE EXCEPTION 'invalid governance scope' USING ERRCODE = '23514';
            END IF;
          ELSIF NEW.domain_package_version_id = '{GOVERNANCE_DOMAIN_ID}'::uuid THEN
            RAISE EXCEPTION 'governance domain only permits org_governance'
              USING ERRCODE = '23514';
          END IF;
          RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_scope_governance
        BEFORE INSERT OR UPDATE OR DELETE ON scope
        FOR EACH ROW EXECUTE FUNCTION kernel_guard_governance_scope()
        """
    )
    op.execute(
        """
        CREATE FUNCTION kernel_guard_work_item_immutable() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          IF NEW.definition_bundle_id IS DISTINCT FROM OLD.definition_bundle_id
             OR NEW.created_by_kind IS DISTINCT FROM OLD.created_by_kind
             OR NEW.created_by_ref IS DISTINCT FROM OLD.created_by_ref
             OR NEW.kernel_mode IS DISTINCT FROM OLD.kernel_mode THEN
            RAISE EXCEPTION 'immutable work item identity changed' USING ERRCODE = '55000';
          END IF;
          RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_work_item_immutable
        BEFORE UPDATE ON work_item
        FOR EACH ROW EXECUTE FUNCTION kernel_guard_work_item_immutable()
        """
    )
    op.execute(
        """
        CREATE FUNCTION kernel_validate_governance_pointer() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE target scope%ROWTYPE;
        BEGIN
          IF NEW.governance_state = 'active' THEN
            SELECT * INTO target FROM scope
             WHERE org_id = NEW.org_id AND id = NEW.governance_scope_id;
            IF NOT FOUND OR target.scope_type <> 'org_governance'
               OR target.status <> 'active'
               OR NOT kernel_validate_org_policy(target.attributes) THEN
              RAISE EXCEPTION 'invalid governance pointer' USING ERRCODE = '23514';
            END IF;
          END IF;
          RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER trg_org_kernel_setting_governance_pointer
        AFTER INSERT OR UPDATE ON org_kernel_setting
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION kernel_validate_governance_pointer()
        """
    )
    op.execute(
        """
        INSERT INTO org_kernel_setting (org_id)
        SELECT id FROM org
        ON CONFLICT (org_id) DO NOTHING
        """
    )
    # Drain deferred validation events before ALTER TABLE enables RLS below.
    op.execute("SET CONSTRAINTS trg_org_kernel_setting_governance_pointer IMMEDIATE")
    op.execute(
        """
        CREATE FUNCTION kernel_initialize_org_setting() RETURNS trigger
        LANGUAGE plpgsql SECURITY DEFINER
        SET search_path = pg_catalog, public AS $$
        BEGIN
          INSERT INTO org_kernel_setting (org_id) VALUES (NEW.id)
          ON CONFLICT (org_id) DO NOTHING;
          RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_org_kernel_setting_initialize
        AFTER INSERT ON org
        FOR EACH ROW EXECUTE FUNCTION kernel_initialize_org_setting()
        """
    )

    for table_name in RLS_TABLES:
        op.execute(f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table_name} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY org_isolation ON {table_name} "
            "USING (org_id = NULLIF(current_setting('app.current_org', true), '')::uuid) "
            "WITH CHECK (org_id = NULLIF(current_setting('app.current_org', true), '')::uuid)"
        )


def downgrade() -> None:
    for table_name in reversed(RLS_TABLES):
        op.execute(f"DROP POLICY IF EXISTS org_isolation ON {table_name}")

    op.execute("DROP TRIGGER IF EXISTS trg_org_kernel_setting_initialize ON org")
    op.execute("DROP FUNCTION IF EXISTS kernel_initialize_org_setting()")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_org_kernel_setting_governance_pointer ON org_kernel_setting"
    )
    op.execute("DROP FUNCTION IF EXISTS kernel_validate_governance_pointer()")
    op.execute("DROP TRIGGER IF EXISTS trg_work_item_immutable ON work_item")
    op.execute("DROP FUNCTION IF EXISTS kernel_guard_work_item_immutable()")
    op.execute("DROP TRIGGER IF EXISTS trg_scope_governance ON scope")
    op.execute("DROP FUNCTION IF EXISTS kernel_guard_governance_scope()")
    op.execute("DROP FUNCTION IF EXISTS kernel_validate_org_policy(jsonb)")

    for table_name in (
        "org_kernel_setting",
        "service_identity",
        "work_role_binding",
        "work_item",
        "scope_role_assignment",
        "scope_relation",
        "scope",
    ):
        op.drop_table(table_name)

    op.execute(
        "ALTER TABLE role_definition_version DISABLE TRIGGER trg_role_definition_version_immutable"
    )
    op.execute(
        sa.text(
            "DELETE FROM role_definition_version "
            "WHERE id = CAST(:id AS uuid) AND key = 'kernel.governance_owner'"
        ).bindparams(id=GOVERNANCE_ROLE_ID)
    )
    op.execute(
        "ALTER TABLE role_definition_version ENABLE TRIGGER trg_role_definition_version_immutable"
    )
    op.execute(
        "ALTER TABLE domain_package_version DISABLE TRIGGER trg_domain_package_version_immutable"
    )
    op.execute(
        sa.text(
            "DELETE FROM domain_package_version "
            "WHERE id = CAST(:id AS uuid) AND key = 'kernel.governance'"
        ).bindparams(id=GOVERNANCE_DOMAIN_ID)
    )
    op.execute(
        "ALTER TABLE domain_package_version ENABLE TRIGGER trg_domain_package_version_immutable"
    )
