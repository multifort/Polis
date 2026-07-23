"""K1-T2 PostgreSQL contracts for Definition versions and compiled bundles."""

from __future__ import annotations

import asyncio
import copy
import json
import uuid
from pathlib import Path
from typing import Any, cast

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Table, create_engine, inspect, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import polis.db.models as model_registry
from polis.db.models import Base
from polis.modules.kernel.errors import KernelProtocolError
from polis.modules.kernel.models import (
    DefinitionBundle,
    DefinitionBundleDependency,
    DefinitionBundleRole,
    DomainPackageVersion,
    RoleDefinitionVersion,
    WorkDefinitionVersion,
)
from polis.modules.kernel.repository import (
    DefinitionKind,
    get_bundle,
    get_visible_definition,
)
from polis.modules.kernel.repository import (
    _add_bundle_snapshot as add_bundle_snapshot,
)
from polis.modules.kernel.repository import (
    _create_definition_draft as create_definition_draft,
)
from polis.modules.kernel.repository import (
    _deprecate_definition as deprecate_definition,
)
from polis.modules.kernel.repository import (
    _publish_definition as publish_definition,
)
from polis.modules.kernel.repository import (
    _update_definition_draft as update_definition_draft,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
FIXTURE_PATH = REPOSITORY_ROOT / "docs/design/v3/kernel/fixtures/generic-definition-set-v1.json"
NEW_TABLES = {
    "domain_package_version",
    "work_definition_version",
    "role_definition_version",
    "definition_bundle",
    "definition_bundle_role",
    "definition_bundle_dependency",
}


def _fixture() -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(FIXTURE_PATH.read_text(encoding="utf-8")))


def _sync_url(pg_url: str) -> str:
    return pg_url.replace("+asyncpg", "+psycopg2")


def _create_tenants(pg_url: str) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    engine = create_engine(_sync_url(pg_url))
    try:
        with engine.begin() as connection:
            user_id = connection.execute(
                text("INSERT INTO app_user (email) VALUES (:email) RETURNING id"),
                {"email": f"kernel_{uuid.uuid4().hex}@polis.dev"},
            ).scalar_one()
            org_a = connection.execute(
                text("INSERT INTO org (name, owner_user_id) VALUES (:name, :user) RETURNING id"),
                {"name": f"Kernel A {uuid.uuid4().hex[:6]}", "user": user_id},
            ).scalar_one()
            org_b = connection.execute(
                text("INSERT INTO org (name, owner_user_id) VALUES (:name, :user) RETURNING id"),
                {"name": f"Kernel B {uuid.uuid4().hex[:6]}", "user": user_id},
            ).scalar_one()
            return user_id, org_a, org_b
    finally:
        engine.dispose()


def test_models_are_registered_with_explicit_physical_tables() -> None:
    assert model_registry.kernel_models is not None
    assert set(Base.metadata.tables) >= NEW_TABLES
    assert DomainPackageVersion.__tablename__ == "domain_package_version"
    assert WorkDefinitionVersion.__tablename__ == "work_definition_version"
    assert RoleDefinitionVersion.__tablename__ == "role_definition_version"
    domain_table = cast(Table, DomainPackageVersion.__table__)
    assert {index.name for index in domain_table.indexes if index.unique} == {
        "uq_domain_package_version_public_key_version",
        "uq_domain_package_version_private_key_version",
    }


def test_definition_repository_visibility_lifecycle_and_db_immutability(pg_url: str) -> None:
    user_id, org_a, org_b = _create_tenants(pg_url)
    source = _fixture()["domain_package"]

    async def exercise() -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
        engine = create_async_engine(pg_url)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with factory() as session:
                private_a = await create_definition_draft(
                    session,
                    kind="domain_package",
                    owner_org_id=org_a,
                    key=source["key"],
                    version="1.0.0",
                    visibility="private",
                    definition=source,
                    created_by=user_id,
                )
                private_b = await create_definition_draft(
                    session,
                    kind="domain_package",
                    owner_org_id=org_b,
                    key=source["key"],
                    version="1.0.0",
                    visibility="private",
                    definition=source,
                    created_by=user_id,
                )
                public = await create_definition_draft(
                    session,
                    kind="domain_package",
                    owner_org_id=None,
                    key=source["key"],
                    version="1.0.0",
                    visibility="public",
                    definition=source,
                    created_by=user_id,
                )
                with pytest.raises(KernelProtocolError, match="DEFINITION_ALREADY_EXISTS"):
                    await create_definition_draft(
                        session,
                        kind="domain_package",
                        owner_org_id=org_a,
                        key=source["key"],
                        version="1.0.0",
                        visibility="private",
                        definition=source,
                        created_by=user_id,
                    )

                assert (
                    await get_visible_definition(
                        session,
                        kind="domain_package",
                        definition_id=private_a.id,
                        org_id=org_b,
                    )
                    is None
                )
                assert (
                    await get_visible_definition(
                        session,
                        kind="domain_package",
                        definition_id=private_b.id,
                        org_id=org_b,
                    )
                    is private_b
                )
                assert (
                    await get_visible_definition(
                        session,
                        kind="domain_package",
                        definition_id=public.id,
                        org_id=org_a,
                    )
                    is public
                )

                updated_definition = copy.deepcopy(source)
                updated_definition["display_name"] = "更新后的通用领域包"
                updated = await update_definition_draft(
                    session,
                    kind="domain_package",
                    definition_id=private_a.id,
                    owner_org_id=org_a,
                    expected_revision=1,
                    definition=updated_definition,
                )
                assert updated.revision == 2
                published = await publish_definition(
                    session,
                    kind="domain_package",
                    definition_id=private_a.id,
                    owner_org_id=org_a,
                    expected_revision=2,
                )
                assert published.status == "published"
                assert published.published_at is not None
                with pytest.raises(KernelProtocolError, match="DEFINITION_IMMUTABLE"):
                    await update_definition_draft(
                        session,
                        kind="domain_package",
                        definition_id=private_a.id,
                        owner_org_id=org_a,
                        expected_revision=2,
                        definition=source,
                    )
                await session.commit()
                published_id = private_a.id
                private_b_id = private_b.id
                public_id = public.id

            async with factory() as session:
                deprecated = await deprecate_definition(
                    session,
                    kind="domain_package",
                    definition_id=published_id,
                    owner_org_id=org_a,
                )
                assert deprecated.status == "deprecated"
                assert deprecated.revision == 2
                await session.commit()
            return published_id, private_b_id, public_id
        finally:
            await engine.dispose()

    published_id, private_b_id, public_id = asyncio.run(exercise())

    engine = create_engine(_sync_url(pg_url))
    try:
        with engine.connect() as connection:
            connection.execute(text("SET ROLE polis_app"))
            connection.execute(
                text("SELECT set_config('app.current_org', :org, false)"),
                {"org": str(org_a)},
            )
            visible_ids = set(
                connection.execute(text("SELECT id FROM domain_package_version")).scalars()
            )
            assert published_id in visible_ids
            assert public_id in visible_ids
            assert private_b_id not in visible_ids
            assert (
                connection.execute(
                    text("UPDATE domain_package_version SET status = status WHERE id = :id"),
                    {"id": public_id},
                ).rowcount
                == 0
            )
            assert (
                connection.execute(
                    text("DELETE FROM domain_package_version WHERE id = :id"),
                    {"id": public_id},
                ).rowcount
                == 0
            )
            connection.execute(text("RESET ROLE"))

        with pytest.raises(DBAPIError, match="immutable"), engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE domain_package_version "
                    "SET definition = jsonb_set(definition, '{display_name}', '"
                    + '"tampered"'
                    + "') "
                    "WHERE id = :id"
                ),
                {"id": published_id},
            )
        with pytest.raises(DBAPIError, match="cannot be deleted"), engine.begin() as connection:
            connection.execute(
                text("DELETE FROM domain_package_version WHERE id = :id"),
                {"id": published_id},
            )
    finally:
        engine.dispose()


async def _create_published_set(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
) -> tuple[DomainPackageVersion, WorkDefinitionVersion, RoleDefinitionVersion]:
    fixture = _fixture()
    rows = []
    definitions: tuple[tuple[DefinitionKind, dict[str, Any]], ...] = (
        ("domain_package", fixture["domain_package"]),
        ("work", fixture["works"][0]),
        ("role", fixture["roles"][0]),
    )
    for kind, definition in definitions:
        row = await create_definition_draft(
            session,
            kind=kind,
            owner_org_id=org_id,
            key=definition["key"],
            version="1.0.0",
            visibility="private",
            definition=definition,
            created_by=user_id,
        )
        await publish_definition(
            session,
            kind=kind,
            definition_id=row.id,
            owner_org_id=org_id,
            expected_revision=1,
        )
        rows.append(row)
    return cast(
        tuple[DomainPackageVersion, WorkDefinitionVersion, RoleDefinitionVersion], tuple(rows)
    )


def test_bundle_rls_org_filters_and_db_immutability(pg_url: str) -> None:
    user_id, org_a, org_b = _create_tenants(pg_url)

    async def seed_bundles() -> tuple[uuid.UUID, uuid.UUID]:
        engine = create_async_engine(pg_url)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with factory() as session:
                bundle_ids: list[uuid.UUID] = []
                for index, org_id in enumerate((org_a, org_b)):
                    domain, work, role = await _create_published_set(
                        session, org_id=org_id, user_id=user_id
                    )
                    child = DefinitionBundle(
                        org_id=org_id,
                        domain_package_version_id=domain.id,
                        work_definition_version_id=work.id,
                        compiled_definition={"kind": "child"},
                        checksum=chr(ord("a") + index * 2) * 64,
                        compiler_version="1.0.0",
                        kernel_contract_version="3.4",
                        min_kernel_version="3.4.0",
                        child_work_bundle_dependencies={},
                    )
                    await add_bundle_snapshot(session, bundle=child, roles=[], dependencies=[])
                    parent = DefinitionBundle(
                        org_id=org_id,
                        domain_package_version_id=domain.id,
                        work_definition_version_id=work.id,
                        compiled_definition={"kind": "parent"},
                        checksum=chr(ord("b") + index * 2) * 64,
                        compiler_version="1.0.0",
                        kernel_contract_version="3.4",
                        min_kernel_version="3.4.0",
                        child_work_bundle_dependencies={
                            "remediation_v1": {
                                "bundle_id": str(child.id),
                                "checksum": child.checksum,
                            }
                        },
                    )
                    bundle_role = DefinitionBundleRole(
                        org_id=org_id,
                        role_slot_key="owner",
                        role_definition_version_id=role.id,
                    )
                    dependency = DefinitionBundleDependency(
                        org_id=org_id,
                        dependency_key="remediation_v1",
                        trigger_key="create_remediation" if index == 0 else None,
                        child_bundle_id=child.id,
                        child_bundle_checksum=child.checksum,
                    )
                    await add_bundle_snapshot(
                        session,
                        bundle=parent,
                        roles=[bundle_role],
                        dependencies=[dependency],
                    )
                    bundle_ids.append(parent.id)
                await session.commit()

            async with factory() as session:
                assert await get_bundle(session, org_id=org_a, bundle_id=bundle_ids[0]) is not None
                assert await get_bundle(session, org_id=org_a, bundle_id=bundle_ids[1]) is None
            return bundle_ids[0], bundle_ids[1]
        finally:
            await engine.dispose()

    bundle_a, bundle_b = asyncio.run(seed_bundles())

    engine = create_engine(_sync_url(pg_url))
    try:
        with engine.connect() as connection:
            connection.execute(text("SET ROLE polis_app"))
            connection.execute(
                text("SELECT set_config('app.current_org', :org, false)"), {"org": str(org_a)}
            )
            assert set(connection.execute(text("SELECT id FROM definition_bundle")).scalars()) == {
                bundle_a,
                # child bundle is also visible; parent identity proves B is absent below.
                *connection.execute(
                    text("SELECT child_bundle_id FROM definition_bundle_dependency")
                ).scalars(),
            }
            assert bundle_b not in set(
                connection.execute(text("SELECT id FROM definition_bundle")).scalars()
            )
            assert (
                connection.execute(text("SELECT count(*) FROM definition_bundle_role")).scalar_one()
                == 1
            )
            assert (
                connection.execute(
                    text("SELECT count(*) FROM definition_bundle_dependency")
                ).scalar_one()
                == 1
            )

            connection.execute(text("RESET app.current_org"))
            for table_name in (
                "definition_bundle",
                "definition_bundle_role",
                "definition_bundle_dependency",
            ):
                assert (
                    connection.execute(
                        text(f"SELECT count(*) FROM {table_name}")  # noqa: S608 - fixed table names
                    ).scalar_one()
                    == 0
                )
            connection.execute(text("RESET ROLE"))

        with pytest.raises(DBAPIError, match="bundles are immutable"), engine.begin() as connection:
            connection.execute(
                text("UPDATE definition_bundle SET compiler_version = '9.9.9' WHERE id = :id"),
                {"id": bundle_a},
            )
    finally:
        engine.dispose()


def test_zz_migration_downgrade_upgrade_and_metadata_match(pg_url: str) -> None:
    del pg_url
    config = Config("alembic.ini")
    command.downgrade(config, "8c9d0e1f2a3b")
    database_url = config.get_main_option("sqlalchemy.url")
    assert database_url is not None
    engine = create_engine(database_url.replace("+asyncpg", "+psycopg2"))
    try:
        assert NEW_TABLES.isdisjoint(inspect(engine).get_table_names())
    finally:
        engine.dispose()
    command.upgrade(config, "head")
    command.check(config)
