"""V3 K1 Definition versions and immutable compiled bundles.

Revision ID: 9d0e1f2a3b4c
Revises: 8c9d0e1f2a3b
Create Date: 2026-07-22 09:50:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "9d0e1f2a3b4c"
down_revision: str | None = "8c9d0e1f2a3b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DEFINITION_TABLES = (
    ("domain_package_version", "domain_package"),
    ("work_definition_version", "work"),
    ("role_definition_version", "role"),
)
DEFINITION_RLS_TABLES = tuple(table_name for table_name, _ in DEFINITION_TABLES)
RLS_TABLES = (
    "definition_bundle",
    "definition_bundle_role",
    "definition_bundle_dependency",
)


def _create_definition_table(table_name: str, definition_kind: str) -> None:
    op.create_table(
        table_name,
        sa.Column(
            "owner_org_id",
            sa.Uuid(),
            sa.ForeignKey("org.id"),
            nullable=True,
        ),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("version", sa.Text(), nullable=False),
        sa.Column("visibility", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="draft"),
        sa.Column("schema_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("definition", JSONB(), nullable=False),
        sa.Column("checksum", sa.Text(), nullable=False),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("app_user.id"), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "id",
            sa.Uuid(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
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
        sa.CheckConstraint(
            f"definition ->> 'definition_kind' = '{definition_kind}'",
            name=op.f(f"ck_{table_name}_definition_kind"),
        ),
        sa.CheckConstraint(
            "checksum ~ '^[0-9a-f]{64}$'",
            name=op.f(f"ck_{table_name}_checksum_format"),
        ),
        sa.CheckConstraint("revision >= 1", name=op.f(f"ck_{table_name}_revision")),
        sa.CheckConstraint("schema_version = 1", name=op.f(f"ck_{table_name}_schema_version")),
        sa.CheckConstraint(
            "status IN ('draft','published','deprecated')",
            name=op.f(f"ck_{table_name}_status"),
        ),
        sa.CheckConstraint(
            "(status = 'draft' AND published_at IS NULL) OR "
            "(status IN ('published','deprecated') AND published_at IS NOT NULL)",
            name=op.f(f"ck_{table_name}_status_published_at"),
        ),
        sa.CheckConstraint(
            "visibility IN ('public','private')",
            name=op.f(f"ck_{table_name}_visibility"),
        ),
        sa.CheckConstraint(
            "(visibility = 'public' AND owner_org_id IS NULL) OR "
            "(visibility = 'private' AND owner_org_id IS NOT NULL)",
            name=op.f(f"ck_{table_name}_visibility_owner"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{table_name}")),
    )
    op.create_index(f"ix_{table_name}_checksum", table_name, ["checksum"], unique=False)
    op.create_index(
        f"ix_{table_name}_owner_status",
        table_name,
        ["owner_org_id", "status"],
        unique=False,
    )
    op.create_index(
        f"uq_{table_name}_private_key_version",
        table_name,
        ["owner_org_id", "key", "version"],
        unique=True,
        postgresql_where=sa.text("owner_org_id IS NOT NULL"),
    )
    op.create_index(
        f"uq_{table_name}_public_key_version",
        table_name,
        ["key", "version"],
        unique=True,
        postgresql_where=sa.text("owner_org_id IS NULL"),
    )


def upgrade() -> None:
    for table_name, definition_kind in DEFINITION_TABLES:
        _create_definition_table(table_name, definition_kind)

    op.create_table(
        "definition_bundle",
        sa.Column(
            "domain_package_version_id",
            sa.Uuid(),
            sa.ForeignKey("domain_package_version.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "work_definition_version_id",
            sa.Uuid(),
            sa.ForeignKey("work_definition_version.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("compiled_definition", JSONB(), nullable=False),
        sa.Column("checksum", sa.Text(), nullable=False),
        sa.Column("compiler_version", sa.Text(), nullable=False),
        sa.Column("kernel_contract_version", sa.Text(), nullable=False),
        sa.Column("min_kernel_version", sa.Text(), nullable=False),
        sa.Column(
            "child_work_bundle_dependencies",
            JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
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
        sa.Column(
            "org_id",
            sa.Uuid(),
            sa.ForeignKey("org.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "checksum ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_definition_bundle_checksum_format"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_definition_bundle")),
        sa.UniqueConstraint("org_id", "checksum", name=op.f("uq_definition_bundle_org_checksum")),
        sa.UniqueConstraint("org_id", "id", name=op.f("uq_definition_bundle_org_id_id")),
    )
    op.create_index(
        "ix_definition_bundle_org_domain_version",
        "definition_bundle",
        ["org_id", "domain_package_version_id"],
        unique=False,
    )
    op.create_index(
        "ix_definition_bundle_org_work_version",
        "definition_bundle",
        ["org_id", "work_definition_version_id"],
        unique=False,
    )
    op.create_index("ix_definition_bundle_org_id", "definition_bundle", ["org_id"])

    op.create_table(
        "definition_bundle_role",
        sa.Column(
            "org_id",
            sa.Uuid(),
            sa.ForeignKey("org.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("bundle_id", sa.Uuid(), nullable=False),
        sa.Column("role_slot_key", sa.Text(), nullable=False),
        sa.Column(
            "role_definition_version_id",
            sa.Uuid(),
            sa.ForeignKey("role_definition_version.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ("org_id", "bundle_id"),
            ("definition_bundle.org_id", "definition_bundle.id"),
            ondelete="CASCADE",
            name=op.f("fk_definition_bundle_role_org_bundle"),
        ),
        sa.PrimaryKeyConstraint(
            "bundle_id", "role_slot_key", name=op.f("pk_definition_bundle_role")
        ),
    )
    op.create_index("ix_definition_bundle_role_org_id", "definition_bundle_role", ["org_id"])

    op.create_table(
        "definition_bundle_dependency",
        sa.Column(
            "org_id",
            sa.Uuid(),
            sa.ForeignKey("org.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("parent_bundle_id", sa.Uuid(), nullable=False),
        sa.Column("dependency_key", sa.Text(), nullable=False),
        sa.Column("trigger_key", sa.Text(), nullable=False),
        sa.Column("child_bundle_id", sa.Uuid(), nullable=False),
        sa.Column("child_bundle_checksum", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "child_bundle_checksum ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_definition_bundle_dependency_checksum_format"),
        ),
        sa.ForeignKeyConstraint(
            ("org_id", "child_bundle_id"),
            ("definition_bundle.org_id", "definition_bundle.id"),
            ondelete="RESTRICT",
            name=op.f("fk_definition_bundle_dependency_child_bundle"),
        ),
        sa.ForeignKeyConstraint(
            ("org_id", "parent_bundle_id"),
            ("definition_bundle.org_id", "definition_bundle.id"),
            ondelete="CASCADE",
            name=op.f("fk_definition_bundle_dependency_parent_bundle"),
        ),
        sa.PrimaryKeyConstraint(
            "org_id",
            "parent_bundle_id",
            "dependency_key",
            name=op.f("pk_definition_bundle_dependency"),
        ),
        sa.UniqueConstraint(
            "org_id",
            "parent_bundle_id",
            "trigger_key",
            name=op.f("uq_definition_bundle_dependency_parent_trigger"),
        ),
    )

    op.execute(
        """
        CREATE FUNCTION kernel_guard_definition_immutable() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_OP = 'DELETE' THEN
            IF OLD.status <> 'draft' THEN
              RAISE EXCEPTION 'published or deprecated definitions cannot be deleted'
                USING ERRCODE = '55000';
            END IF;
            RETURN OLD;
          END IF;
          IF OLD.status IN ('published', 'deprecated') THEN
            IF NEW.owner_org_id IS DISTINCT FROM OLD.owner_org_id
              OR NEW.key IS DISTINCT FROM OLD.key
              OR NEW.version IS DISTINCT FROM OLD.version
              OR NEW.visibility IS DISTINCT FROM OLD.visibility
              OR NEW.schema_version IS DISTINCT FROM OLD.schema_version
              OR NEW.revision IS DISTINCT FROM OLD.revision
              OR NEW.definition IS DISTINCT FROM OLD.definition
              OR NEW.checksum IS DISTINCT FROM OLD.checksum
              OR NEW.created_by IS DISTINCT FROM OLD.created_by
              OR NEW.created_at IS DISTINCT FROM OLD.created_at
              OR NEW.published_at IS DISTINCT FROM OLD.published_at THEN
              RAISE EXCEPTION 'published definition content is immutable'
                USING ERRCODE = '55000';
            END IF;
            IF OLD.status = 'deprecated' AND NEW.status <> 'deprecated' THEN
              RAISE EXCEPTION 'deprecated definition status is immutable'
                USING ERRCODE = '55000';
            END IF;
            IF OLD.status = 'published' AND NEW.status NOT IN ('published', 'deprecated') THEN
              RAISE EXCEPTION 'published definition can only be deprecated'
                USING ERRCODE = '55000';
            END IF;
          END IF;
          RETURN NEW;
        END;
        $$
        """
    )
    for table_name, _ in DEFINITION_TABLES:
        op.execute(
            f"CREATE TRIGGER trg_{table_name}_immutable "
            f"BEFORE UPDATE OR DELETE ON {table_name} "
            "FOR EACH ROW EXECUTE FUNCTION kernel_guard_definition_immutable()"
        )

    for table_name in DEFINITION_RLS_TABLES:
        current_org = "NULLIF(current_setting('app.current_org', true), '')::uuid"
        op.execute(f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table_name} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY definition_visible ON {table_name} FOR SELECT USING ("
            "(owner_org_id IS NULL AND visibility = 'public') OR "
            f"owner_org_id = {current_org})"
        )
        op.execute(
            f"CREATE POLICY definition_owner_insert ON {table_name} FOR INSERT "
            f"WITH CHECK (owner_org_id = {current_org})"
        )
        op.execute(
            f"CREATE POLICY definition_owner_update ON {table_name} FOR UPDATE "
            f"USING (owner_org_id = {current_org}) "
            f"WITH CHECK (owner_org_id = {current_org})"
        )
        op.execute(
            f"CREATE POLICY definition_owner_delete ON {table_name} FOR DELETE "
            f"USING (owner_org_id = {current_org})"
        )

    op.execute(
        """
        CREATE FUNCTION kernel_guard_bundle_immutable() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          RAISE EXCEPTION 'definition bundles are immutable'
            USING ERRCODE = '55000';
        END;
        $$
        """
    )
    for table_name in RLS_TABLES:
        op.execute(
            f"CREATE TRIGGER trg_{table_name}_immutable "
            f"BEFORE UPDATE OR DELETE ON {table_name} "
            "FOR EACH ROW EXECUTE FUNCTION kernel_guard_bundle_immutable()"
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
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table_name}_immutable ON {table_name}")
    op.execute("DROP FUNCTION IF EXISTS kernel_guard_bundle_immutable()")
    for table_name in DEFINITION_RLS_TABLES:
        for policy_name in (
            "definition_owner_delete",
            "definition_owner_update",
            "definition_owner_insert",
            "definition_visible",
        ):
            op.execute(f"DROP POLICY IF EXISTS {policy_name} ON {table_name}")
    for table_name, _ in DEFINITION_TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table_name}_immutable ON {table_name}")
    op.execute("DROP FUNCTION IF EXISTS kernel_guard_definition_immutable()")

    op.drop_table("definition_bundle_dependency")
    op.drop_index("ix_definition_bundle_role_org_id", table_name="definition_bundle_role")
    op.drop_table("definition_bundle_role")
    op.drop_index("ix_definition_bundle_org_id", table_name="definition_bundle")
    op.drop_index("ix_definition_bundle_org_work_version", table_name="definition_bundle")
    op.drop_index("ix_definition_bundle_org_domain_version", table_name="definition_bundle")
    op.drop_table("definition_bundle")

    for table_name, _ in reversed(DEFINITION_TABLES):
        op.drop_index(f"uq_{table_name}_public_key_version", table_name=table_name)
        op.drop_index(f"uq_{table_name}_private_key_version", table_name=table_name)
        op.drop_index(f"ix_{table_name}_owner_status", table_name=table_name)
        op.drop_index(f"ix_{table_name}_checksum", table_name=table_name)
        op.drop_table(table_name)
