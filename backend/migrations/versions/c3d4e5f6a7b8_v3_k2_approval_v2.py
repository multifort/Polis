"""V3 K2 Approval V2 snapshot and append-only decisions.

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-07-23
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

revision: str = "c3d4e5f6a7b8"
down_revision: str | None = "b2c3d4e5f6a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(op.f("ck_approval_kind"), "approval", type_="check")
    op.drop_constraint(op.f("ck_approval_status"), "approval", type_="check")
    op.alter_column("approval", "kind", existing_type=sa.Text(), nullable=True)
    op.add_column(
        "approval",
        sa.Column("approval_schema_version", sa.Integer(), server_default="1", nullable=False),
    )
    op.add_column("approval", sa.Column("command_family", sa.Text(), nullable=True))
    op.add_column(
        "approval",
        sa.Column("domain_package_version_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "approval",
        sa.Column("work_definition_version_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "approval",
        sa.Column("role_definition_version_id", sa.Uuid(), nullable=True),
    )
    op.add_column("approval", sa.Column("scope_id", sa.Uuid(), nullable=True))
    op.add_column("approval", sa.Column("work_item_id", sa.Uuid(), nullable=True))
    op.add_column("approval", sa.Column("command_type", sa.Text(), nullable=True))
    op.add_column("approval", sa.Column("command_fingerprint", sa.Text(), nullable=True))
    op.add_column("approval", sa.Column("approval_purpose", sa.Text(), nullable=True))
    op.add_column("approval", sa.Column("version", sa.Integer(), nullable=True))
    op.add_column("approval", sa.Column("requested_by_kind", sa.Text(), nullable=True))
    op.add_column("approval", sa.Column("requested_by_ref", sa.Uuid(), nullable=True))
    op.add_column(
        "approval",
        sa.Column("required_role_slots", ARRAY(sa.Text()), nullable=True),
    )
    op.add_column(
        "approval",
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("approval", sa.Column("decision_reason", sa.Text(), nullable=True))
    op.add_column("approval", sa.Column("decided_by_kind", sa.Text(), nullable=True))
    op.add_column("approval", sa.Column("decided_by_ref", sa.Uuid(), nullable=True))
    op.add_column("approval", sa.Column("consumed_by_command_id", sa.Uuid(), nullable=True))
    op.add_column("approval", sa.Column("command_receipt_id", sa.Uuid(), nullable=True))
    op.add_column("approval", sa.Column("resume_mode", sa.Text(), nullable=True))
    op.add_column(
        "approval",
        sa.Column("payload_snapshot", JSONB(), nullable=True),
    )
    op.create_unique_constraint(
        "uq_approval_org_id_id",
        "approval",
        ["org_id", "id"],
    )
    op.create_foreign_key(
        "fk_approval_domain_package_version_id_domain_package_version",
        "approval",
        "domain_package_version",
        ["domain_package_version_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_approval_work_definition_version_id_work_definition_version",
        "approval",
        "work_definition_version",
        ["work_definition_version_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_approval_role_definition_version_id_role_definition_version",
        "approval",
        "role_definition_version",
        ["role_definition_version_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_approval_org_scope",
        "approval",
        "scope",
        ["org_id", "scope_id"],
        ["org_id", "id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_approval_org_work",
        "approval",
        "work_item",
        ["org_id", "work_item_id"],
        ["org_id", "id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        op.f("ck_approval_kind"),
        "approval",
        "(approval_schema_version = 1 AND kind IN "
        "('plan','dangerous_action','provision_review','skill_review','rework')) OR "
        "(approval_schema_version = 2 AND kind IS NULL)",
    )
    op.create_check_constraint(
        op.f("ck_approval_status"),
        "approval",
        "(approval_schema_version = 1 AND status IN "
        "('pending','approved','rejected')) OR "
        "(approval_schema_version = 2 AND status IN "
        "('pending','approved','rejected','expired','revoked','consumed'))",
    )
    op.create_check_constraint(
        op.f("ck_approval_schema_version"),
        "approval",
        "approval_schema_version IN (1,2)",
    )
    op.create_check_constraint(
        op.f("ck_approval_v2_contract"),
        "approval",
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
    )
    op.create_check_constraint(
        op.f("ck_approval_v2_state"),
        "approval",
        "approval_schema_version = 1 OR ("
        "(status = 'pending' AND decided_by_kind IS NULL AND decided_by_ref IS NULL "
        "AND decided_at IS NULL AND consumed_by_command_id IS NULL) OR "
        "(status IN ('approved','rejected','expired','revoked') "
        "AND decided_by_kind IS NOT NULL AND decided_by_ref IS NOT NULL "
        "AND decided_at IS NOT NULL AND consumed_by_command_id IS NULL) OR "
        "(status = 'consumed' AND decided_by_kind IS NOT NULL "
        "AND decided_by_ref IS NOT NULL AND decided_at IS NOT NULL "
        "AND consumed_by_command_id IS NOT NULL))",
    )
    op.create_check_constraint(
        op.f("ck_approval_decided_actor_pair"),
        "approval",
        "(decided_by_kind IS NULL) = (decided_by_ref IS NULL)",
    )
    op.create_index(
        "ix_approval_org_family_status_expires",
        "approval",
        ["org_id", "command_family", "status", "expires_at"],
    )
    op.create_index(
        "uq_approval_v2_org_receipt",
        "approval",
        ["org_id", "command_receipt_id"],
        unique=True,
        postgresql_where=sa.text("approval_schema_version = 2"),
    )
    op.create_index(
        "uq_approval_v2_org_consumed_command",
        "approval",
        ["org_id", "consumed_by_command_id"],
        unique=True,
        postgresql_where=sa.text("consumed_by_command_id IS NOT NULL"),
    )

    op.create_table(
        "approval_decision",
        sa.Column("approval_id", sa.Uuid(), nullable=False),
        sa.Column("approval_version", sa.Integer(), nullable=False),
        sa.Column("family_command_id", sa.Uuid(), nullable=False),
        sa.Column("requested_action", sa.Text(), nullable=False),
        sa.Column("outcome_status", sa.Text(), nullable=False),
        sa.Column("decided_by_kind", sa.Text(), nullable=False),
        sa.Column("decided_by_ref", sa.Uuid(), nullable=False),
        sa.Column("reason_code", sa.Text(), nullable=True),
        sa.Column("reason_note", sa.Text(), nullable=True),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "id",
            sa.Uuid(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "requested_action IN ('approve','reject','expire','revoke','consume')",
            name="ck_approval_decision_requested_action",
        ),
        sa.CheckConstraint(
            "outcome_status IN ('approved','rejected','expired','revoked','consumed')",
            name="ck_approval_decision_outcome_status",
        ),
        sa.CheckConstraint(
            "approval_version >= 2",
            name="ck_approval_decision_approval_version",
        ),
        sa.CheckConstraint(
            "decided_by_kind IN ('human','agent','service')",
            name="ck_approval_decision_decided_by_kind",
        ),
        sa.ForeignKeyConstraint(
            ["org_id", "approval_id"],
            ["approval.org_id", "approval.id"],
            name="fk_approval_decision_org_approval",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["org.id"],
            name="fk_approval_decision_org_id_org",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_approval_decision"),
        sa.UniqueConstraint(
            "org_id",
            "approval_id",
            "approval_version",
            name="uq_approval_decision_org_approval_version",
        ),
        sa.UniqueConstraint(
            "org_id",
            "family_command_id",
            name="uq_approval_decision_org_family_command",
        ),
    )
    op.create_index(
        "ix_approval_decision_org_id",
        "approval_decision",
        ["org_id"],
    )
    op.create_index(
        "ix_approval_decision_org_approval",
        "approval_decision",
        ["org_id", "approval_id"],
    )
    op.execute("ALTER TABLE approval_decision ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE approval_decision FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY org_isolation ON approval_decision "
        "USING (org_id = NULLIF(current_setting('app.current_org', true), '')::uuid) "
        "WITH CHECK (org_id = NULLIF(current_setting('app.current_org', true), '')::uuid)"
    )
    op.execute(
        """
        CREATE FUNCTION kernel_guard_approval_decision_append_only() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          RAISE EXCEPTION 'approval_decision cannot be updated'
            USING ERRCODE = '55000';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_approval_decision_append_only
        BEFORE UPDATE ON approval_decision
        FOR EACH ROW EXECUTE FUNCTION kernel_guard_approval_decision_append_only()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_approval_decision_append_only ON approval_decision")
    op.execute("DROP FUNCTION IF EXISTS kernel_guard_approval_decision_append_only()")
    op.execute("DROP POLICY IF EXISTS org_isolation ON approval_decision")
    op.drop_table("approval_decision")
    # This revision was exercised locally before the two uniqueness guards were
    # added.  IF EXISTS keeps downgrade usable for those pre-release databases.
    op.execute("DROP INDEX IF EXISTS uq_approval_v2_org_consumed_command")
    op.execute("DROP INDEX IF EXISTS uq_approval_v2_org_receipt")
    op.drop_index("ix_approval_org_family_status_expires", table_name="approval")
    op.drop_constraint(op.f("ck_approval_decided_actor_pair"), "approval", type_="check")
    op.drop_constraint(op.f("ck_approval_v2_contract"), "approval", type_="check")
    op.execute("ALTER TABLE approval DROP CONSTRAINT IF EXISTS ck_approval_v2_state")
    op.drop_constraint(op.f("ck_approval_schema_version"), "approval", type_="check")
    op.drop_constraint(op.f("ck_approval_status"), "approval", type_="check")
    op.drop_constraint(op.f("ck_approval_kind"), "approval", type_="check")
    op.drop_constraint("fk_approval_org_work", "approval", type_="foreignkey")
    op.drop_constraint("fk_approval_org_scope", "approval", type_="foreignkey")
    op.drop_constraint(
        "fk_approval_role_definition_version_id_role_definition_version",
        "approval",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_approval_work_definition_version_id_work_definition_version",
        "approval",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_approval_domain_package_version_id_domain_package_version",
        "approval",
        type_="foreignkey",
    )
    op.drop_constraint("uq_approval_org_id_id", "approval", type_="unique")
    for column_name in (
        "payload_snapshot",
        "resume_mode",
        "command_receipt_id",
        "consumed_by_command_id",
        "decided_by_ref",
        "decided_by_kind",
        "decision_reason",
        "expires_at",
        "required_role_slots",
        "requested_by_ref",
        "requested_by_kind",
        "version",
        "approval_purpose",
        "command_fingerprint",
        "command_type",
        "work_item_id",
        "scope_id",
        "role_definition_version_id",
        "work_definition_version_id",
        "domain_package_version_id",
        "command_family",
        "approval_schema_version",
    ):
        op.drop_column("approval", column_name)
    op.alter_column("approval", "kind", existing_type=sa.Text(), nullable=False)
    op.create_check_constraint(
        op.f("ck_approval_kind"),
        "approval",
        "kind IN ('plan','dangerous_action','provision_review','skill_review','rework')",
    )
    op.create_check_constraint(
        op.f("ck_approval_status"),
        "approval",
        "status IN ('pending','approved','rejected')",
    )
