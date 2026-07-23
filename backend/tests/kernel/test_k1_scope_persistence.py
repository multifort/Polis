"""K1-T4 PostgreSQL invariants for Scope, responsibility and WorkItem."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import Connection, create_engine, inspect, text
from sqlalchemy.exc import DBAPIError

from polis.modules.kernel.domain.governance import (
    GOVERNANCE_DOMAIN_CHECKSUM,
    GOVERNANCE_OWNER_ROLE_CHECKSUM,
)

NEW_TABLES = {
    "scope",
    "scope_relation",
    "scope_role_assignment",
    "work_item",
    "work_role_binding",
    "service_identity",
    "org_kernel_setting",
}
GOVERNANCE_DOMAIN_ID = uuid.UUID("00000000-0000-4000-8000-000000000301")


def _sync_url(pg_url: str) -> str:
    return pg_url.replace("+asyncpg", "+psycopg2")


def _policy() -> str:
    return (
        '{"kernel_policy":{"schema_version":1,"max_concurrent_runs":20,'
        '"budget_limit_cents":0,"budget_enforcement":"observe",'
        '"default_approval_ttl_seconds":86400}}'
    )


def test_scope_tables_seeds_org_initialization_and_governance_guards(pg_url: str) -> None:
    engine = create_engine(_sync_url(pg_url))
    try:
        assert set(inspect(engine).get_table_names()) >= NEW_TABLES
        with engine.begin() as connection:
            seed_rows = connection.execute(
                text(
                    "SELECT key, checksum FROM domain_package_version "
                    "WHERE key = 'kernel.governance' "
                    "UNION ALL "
                    "SELECT key, checksum FROM role_definition_version "
                    "WHERE key = 'kernel.governance_owner'"
                )
            ).all()
            assert set(seed_rows) == {
                ("kernel.governance", GOVERNANCE_DOMAIN_CHECKSUM),
                ("kernel.governance_owner", GOVERNANCE_OWNER_ROLE_CHECKSUM),
            }

            user_id = connection.execute(
                text("INSERT INTO app_user (email) VALUES (:email) RETURNING id"),
                {"email": f"scope_{uuid.uuid4().hex}@polis.dev"},
            ).scalar_one()
            org_id = connection.execute(
                text(
                    "INSERT INTO org (name, owner_user_id) VALUES ('Scope A', :user) RETURNING id"
                ),
                {"user": user_id},
            ).scalar_one()
            assert connection.execute(
                text(
                    "SELECT kernel_mode, governance_state, governance_scope_id "
                    "FROM org_kernel_setting WHERE org_id = :org"
                ),
                {"org": org_id},
            ).one() == ("legacy", "uninitialized", None)

            scope_id = connection.execute(
                text(
                    "INSERT INTO scope "
                    "(org_id,domain_package_version_id,scope_type,display_name,attributes) "
                    "VALUES (:org,:domain,'org_governance','Organization Governance',"
                    "CAST(:policy AS jsonb)) RETURNING id"
                ),
                {"org": org_id, "domain": GOVERNANCE_DOMAIN_ID, "policy": _policy()},
            ).scalar_one()
            connection.execute(
                text(
                    "UPDATE org_kernel_setting SET governance_state='active', "
                    "governance_scope_id=:scope WHERE org_id=:org"
                ),
                {"org": org_id, "scope": scope_id},
            )

        with engine.begin() as connection, pytest.raises(DBAPIError):
            user_id = connection.execute(text("SELECT owner_user_id FROM org LIMIT 1")).scalar_one()
            org_id = connection.execute(
                text("SELECT id FROM org WHERE owner_user_id=:user LIMIT 1"),
                {"user": user_id},
            ).scalar_one()
            connection.execute(
                text(
                    "INSERT INTO scope "
                    "(org_id,domain_package_version_id,scope_type,display_name,attributes) "
                    "VALUES (:org,:domain,'org_governance','Wrong',CAST(:policy AS jsonb))"
                ),
                {"org": org_id, "domain": GOVERNANCE_DOMAIN_ID, "policy": _policy()},
            )
    finally:
        engine.dispose()


def test_scope_cross_org_foreign_keys_reject_tenant_mixing(pg_url: str) -> None:
    engine = create_engine(_sync_url(pg_url))
    try:
        with engine.begin() as connection:
            user_id = connection.execute(
                text("INSERT INTO app_user (email) VALUES (:email) RETURNING id"),
                {"email": f"scope_fk_{uuid.uuid4().hex}@polis.dev"},
            ).scalar_one()
            org_a = connection.execute(
                text("INSERT INTO org (name, owner_user_id) VALUES ('A',:user) RETURNING id"),
                {"user": user_id},
            ).scalar_one()
            org_b = connection.execute(
                text("INSERT INTO org (name, owner_user_id) VALUES ('B',:user) RETURNING id"),
                {"user": user_id},
            ).scalar_one()
            domain_id = connection.execute(
                text(
                    "INSERT INTO domain_package_version "
                    "(owner_org_id,key,version,visibility,status,schema_version,revision,"
                    "definition,checksum,created_by,published_at) VALUES "
                    "(:org,:key,'1.0.0','private','published',1,1,"
                    'CAST(\'{"definition_kind":"domain_package"}\' AS jsonb),'
                    ":checksum,:user,now()) RETURNING id"
                ),
                {
                    "org": org_a,
                    "key": f"test.scope_{uuid.uuid4().hex}",
                    "checksum": "0" * 64,
                    "user": user_id,
                },
            ).scalar_one()
            scope_b = connection.execute(
                text(
                    "INSERT INTO scope "
                    "(org_id,domain_package_version_id,scope_type,display_name,attributes) "
                    "VALUES (:org,:domain,'workspace','B workspace','{}'::jsonb) RETURNING id"
                ),
                {"org": org_b, "domain": domain_id},
            ).scalar_one()

        with engine.begin() as connection, pytest.raises(DBAPIError):
            connection.execute(
                text(
                    "INSERT INTO scope "
                    "(org_id,domain_package_version_id,scope_type,parent_scope_id,"
                    "display_name,attributes) VALUES "
                    "(:org,:domain,'workspace',:parent,'A child','{}'::jsonb)"
                ),
                {
                    "org": org_a,
                    "domain": domain_id,
                    "parent": scope_b,
                },
            )
    finally:
        engine.dispose()


def _seed_rls_graph(
    connection: Connection, *, org_id: uuid.UUID, user_id: uuid.UUID, marker: str
) -> None:
    execute = connection.execute
    domain_id = execute(
        text(
            "INSERT INTO domain_package_version "
            "(owner_org_id,key,version,visibility,status,schema_version,revision,definition,"
            "checksum,created_by,published_at) VALUES "
            "(:org,:key,'1.0.0','private','published',1,1,"
            '\'{"definition_kind":"domain_package"}\'::jsonb,:checksum,:user,now()) '
            "RETURNING id"
        ),
        {
            "org": org_id,
            "key": f"test.rls_{marker}",
            "checksum": marker * 64,
            "user": user_id,
        },
    ).scalar_one()
    work_definition_id = execute(
        text(
            "INSERT INTO work_definition_version "
            "(owner_org_id,key,version,visibility,status,schema_version,revision,definition,"
            "checksum,created_by,published_at) VALUES "
            "(:org,:key,'1.0.0','private','published',1,1,"
            '\'{"definition_kind":"work"}\'::jsonb,:checksum,:user,now()) RETURNING id'
        ),
        {
            "org": org_id,
            "key": f"test.rls_work_{marker}",
            "checksum": ("c" if marker == "a" else "d") * 64,
            "user": user_id,
        },
    ).scalar_one()
    bundle_id = execute(
        text(
            "INSERT INTO definition_bundle "
            "(org_id,domain_package_version_id,work_definition_version_id,"
            "compiled_definition,checksum,compiler_version,kernel_contract_version,"
            "min_kernel_version) VALUES "
            "(:org,:domain,:work,'{}'::jsonb,:checksum,'1.0.0','3.4','3.4.0') "
            "RETURNING id"
        ),
        {
            "org": org_id,
            "domain": domain_id,
            "work": work_definition_id,
            "checksum": marker * 63 + "0",
        },
    ).scalar_one()
    scope_a = execute(
        text(
            "INSERT INTO scope "
            "(org_id,domain_package_version_id,scope_type,display_name,attributes) "
            "VALUES (:org,:domain,'workspace','A','{}'::jsonb) RETURNING id"
        ),
        {"org": org_id, "domain": domain_id},
    ).scalar_one()
    scope_b = execute(
        text(
            "INSERT INTO scope "
            "(org_id,domain_package_version_id,scope_type,display_name,attributes) "
            "VALUES (:org,:domain,'workspace','B','{}'::jsonb) RETURNING id"
        ),
        {"org": org_id, "domain": domain_id},
    ).scalar_one()
    execute(
        text(
            "INSERT INTO scope_relation "
            "(org_id,domain_package_version_id,relationship_type,from_scope_id,to_scope_id,"
            "created_by_kind,created_by_ref) VALUES "
            "(:org,:domain,'depends_on',:from_scope,:to_scope,'human',:user)"
        ),
        {
            "org": org_id,
            "domain": domain_id,
            "from_scope": scope_a,
            "to_scope": scope_b,
            "user": user_id,
        },
    )
    assignment_id = execute(
        text(
            "INSERT INTO scope_role_assignment "
            "(org_id,scope_id,role_definition_version_id,actor_kind,actor_ref,"
            "assigned_by_kind,assigned_by_ref,status) VALUES "
            "(:org,:scope,:role,'human',:user,'human',:user,'active') RETURNING id"
        ),
        {
            "org": org_id,
            "scope": scope_a,
            "role": uuid.UUID("00000000-0000-4000-8000-000000000302"),
            "user": user_id,
        },
    ).scalar_one()
    work_item_id = execute(
        text(
            "INSERT INTO work_item "
            "(org_id,scope_id,definition_bundle_id,title,lifecycle_state,"
            "created_by_kind,created_by_ref) VALUES "
            "(:org,:scope,:bundle,'RLS work','draft','human',:user) RETURNING id"
        ),
        {
            "org": org_id,
            "scope": scope_a,
            "bundle": bundle_id,
            "user": user_id,
        },
    ).scalar_one()
    execute(
        text(
            "INSERT INTO work_role_binding "
            "(org_id,work_item_id,role_slot_key,responsible_assignment_id,"
            "responsibility_kind_snapshot) VALUES "
            "(:org,:work,'owner',:assignment,'accountable')"
        ),
        {"org": org_id, "work": work_item_id, "assignment": assignment_id},
    )
    execute(
        text(
            "INSERT INTO service_identity (org_id,key,allowed_command_families) "
            "VALUES (:org,:key,ARRAY['scope']::text[])"
        ),
        {"org": org_id, "key": f"rls_{marker}"},
    )


def test_all_k1_scope_tables_are_rls_isolated(pg_url: str) -> None:
    engine = create_engine(_sync_url(pg_url))
    try:
        with engine.begin() as connection:
            user_id = connection.execute(
                text("INSERT INTO app_user (email) VALUES (:email) RETURNING id"),
                {"email": f"scope_rls_{uuid.uuid4().hex}@polis.dev"},
            ).scalar_one()
            org_a = connection.execute(
                text("INSERT INTO org (name,owner_user_id) VALUES ('RLS A',:u) RETURNING id"),
                {"u": user_id},
            ).scalar_one()
            org_b = connection.execute(
                text("INSERT INTO org (name,owner_user_id) VALUES ('RLS B',:u) RETURNING id"),
                {"u": user_id},
            ).scalar_one()
            _seed_rls_graph(connection, org_id=org_a, user_id=user_id, marker="a")
            _seed_rls_graph(connection, org_id=org_b, user_id=user_id, marker="b")

        with engine.connect() as connection:
            connection.execute(text("SET ROLE polis_app"))
            connection.execute(
                text("SELECT set_config('app.current_org', :org, false)"),
                {"org": str(org_a)},
            )
            for table_name in sorted(NEW_TABLES):
                visible = set(
                    connection.execute(
                        text(
                            f"SELECT DISTINCT org_id FROM {table_name}"  # noqa: S608
                        )
                    ).scalars()
                )
                assert visible == {org_a}, table_name
            connection.execute(text("RESET app.current_org"))
            for table_name in sorted(NEW_TABLES):
                assert (
                    connection.execute(
                        text(f"SELECT count(*) FROM {table_name}")  # noqa: S608
                    ).scalar_one()
                    == 0
                ), table_name
            connection.execute(text("RESET ROLE"))
    finally:
        engine.dispose()


def test_work_item_identity_is_database_immutable(pg_url: str) -> None:
    engine = create_engine(_sync_url(pg_url))
    try:
        with engine.begin() as connection:
            user_id = connection.execute(
                text("INSERT INTO app_user (email) VALUES (:email) RETURNING id"),
                {"email": f"work_immutable_{uuid.uuid4().hex}@polis.dev"},
            ).scalar_one()
            org_id = connection.execute(
                text("INSERT INTO org (name,owner_user_id) VALUES ('Immutable',:u) RETURNING id"),
                {"u": user_id},
            ).scalar_one()
            _seed_rls_graph(connection, org_id=org_id, user_id=user_id, marker="e")
            work_id = connection.execute(
                text("SELECT id FROM work_item WHERE org_id=:org"), {"org": org_id}
            ).scalar_one()

        with (
            pytest.raises(DBAPIError, match="immutable work item identity"),
            engine.begin() as connection,
        ):
            connection.execute(
                text("UPDATE work_item SET created_by_ref=:ref WHERE id=:id"),
                {"ref": uuid.uuid4(), "id": work_id},
            )
    finally:
        engine.dispose()


def test_org_setting_initializes_before_current_org_context_exists(pg_url: str) -> None:
    engine = create_engine(_sync_url(pg_url))
    try:
        with engine.connect() as connection:
            connection.execute(text("SET ROLE polis_app"))
            connection.execute(text("RESET app.current_org"))
            user_id = connection.execute(
                text("INSERT INTO app_user (email) VALUES (:email) RETURNING id"),
                {"email": f"new_org_{uuid.uuid4().hex}@polis.dev"},
            ).scalar_one()
            org_id = connection.execute(
                text(
                    "INSERT INTO org (name,owner_user_id) "
                    "VALUES ('No current org',:user) RETURNING id"
                ),
                {"user": user_id},
            ).scalar_one()
            connection.execute(
                text("SELECT set_config('app.current_org', :org, false)"),
                {"org": str(org_id)},
            )
            assert (
                connection.execute(
                    text("SELECT governance_state FROM org_kernel_setting WHERE org_id=:org"),
                    {"org": org_id},
                ).scalar_one()
                == "uninitialized"
            )
            connection.rollback()
            connection.execute(text("RESET ROLE"))
    finally:
        engine.dispose()
