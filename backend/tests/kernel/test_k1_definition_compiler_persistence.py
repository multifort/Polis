"""K1-T3 command-side locking, persistence and bundle de-duplication."""

from __future__ import annotations

import asyncio
import copy
import json
import uuid
from pathlib import Path
from typing import Any, cast

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from polis.modules.kernel.application.definition_commands import DefinitionCommandService
from polis.modules.kernel.application.definition_compiler import CompileBundleRequest
from polis.modules.kernel.errors import KernelProtocolError
from polis.modules.kernel.models import DefinitionBundle
from polis.modules.kernel.repository import DefinitionKind, get_bundle

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
FIXTURE_PATH = REPOSITORY_ROOT / "docs/design/v3/kernel/fixtures/generic-definition-set-v1.json"


def _fixture() -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(FIXTURE_PATH.read_text(encoding="utf-8")))


def _sync_url(pg_url: str) -> str:
    return pg_url.replace("+asyncpg", "+psycopg2")


def _create_tenant(pg_url: str) -> tuple[uuid.UUID, uuid.UUID]:
    engine = create_engine(_sync_url(pg_url))
    try:
        with engine.begin() as connection:
            user_id = connection.execute(
                text("INSERT INTO app_user (email) VALUES (:email) RETURNING id"),
                {"email": f"compiler_{uuid.uuid4().hex}@polis.dev"},
            ).scalar_one()
            org_id = connection.execute(
                text("INSERT INTO org (name, owner_user_id) VALUES (:name, :user) RETURNING id"),
                {"name": f"Compiler {uuid.uuid4().hex[:6]}", "user": user_id},
            ).scalar_one()
            return user_id, org_id
    finally:
        engine.dispose()


async def _publish_fixture(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    duplicate_child_trigger: bool = False,
) -> tuple[CompileBundleRequest, uuid.UUID]:
    fixture = _fixture()
    if duplicate_child_trigger:
        assessment = fixture["works"][1]
        child_trigger = next(
            trigger
            for trigger in assessment["triggers"]
            if trigger["emit_command"]["command_type"] == "create_child_work"
        )
        duplicate = copy.deepcopy(child_trigger)
        duplicate["key"] = "create_remediation_for_recheck"
        assessment["triggers"].append(duplicate)

    service = DefinitionCommandService(session)
    rows: dict[str, Any] = {}
    definitions: list[tuple[DefinitionKind, dict[str, Any]]] = [
        ("domain_package", fixture["domain_package"]),
        *[("role", role) for role in fixture["roles"]],
        *[("work", work) for work in fixture["works"]],
    ]
    for kind, definition in definitions:
        version = "1.0.1" if duplicate_child_trigger and kind == "work" else "1.0.0"
        row = await service.create_draft(
            kind=kind,
            owner_org_id=org_id,
            key=definition["key"],
            version=version,
            visibility="private",
            definition=definition,
            created_by=user_id,
        )
        await service.publish(
            kind=kind,
            definition_id=row.id,
            owner_org_id=org_id,
            expected_revision=1,
        )
        rows[definition["key"]] = row

    def request_for(
        work_key: str,
        children: dict[str, CompileBundleRequest],
    ) -> CompileBundleRequest:
        work_definition = next(work for work in fixture["works"] if work["key"] == work_key)
        return CompileBundleRequest(
            domain_package_version_id=rows["core.generic"].id,
            work_definition_version_id=rows[work_key].id,
            role_versions_by_slot={
                slot["key"]: rows[slot["role_definition_key"]].id
                for slot in work_definition["role_slots"]
            },
            child_dependencies_by_key=children,
        )

    child = request_for("core.remediation", {})
    parent = request_for("core.assessment", {"remediation_v1": child})
    return parent, rows["core.assessment"].id


def test_command_service_compiles_and_reuses_complete_bundle_graph(pg_url: str) -> None:
    user_id, org_id = _create_tenant(pg_url)

    async def exercise() -> None:
        engine = create_async_engine(pg_url)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with factory() as session:
                request, work_version_id = await _publish_fixture(
                    session,
                    org_id=org_id,
                    user_id=user_id,
                )
                service = DefinitionCommandService(session)
                first = await service.compile_definition_bundle(
                    org_id=org_id,
                    request=request,
                )
                repeated = await service.compile_definition_bundle(
                    org_id=org_id,
                    request=request,
                )
                assert first.id == repeated.id
                assert (
                    await session.scalar(
                        text("SELECT count(*) FROM definition_bundle WHERE org_id = :org_id"),
                        {"org_id": org_id},
                    )
                    == 2
                )
                assert (
                    await session.scalar(
                        text(
                            "SELECT count(*) FROM definition_bundle_dependency "
                            "WHERE org_id = :org_id"
                        ),
                        {"org_id": org_id},
                    )
                    == 1
                )

                await service.deprecate(
                    kind="work",
                    definition_id=work_version_id,
                    owner_org_id=org_id,
                )
                with pytest.raises(KernelProtocolError) as caught:
                    await service.compile_definition_bundle(
                        org_id=org_id,
                        request=request,
                    )
                assert caught.value.code == "DEFINITION_NOT_PUBLISHED"
                assert (
                    await get_bundle(
                        session,
                        org_id=org_id,
                        bundle_id=first.id,
                    )
                    is first
                )
                await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(exercise())


def test_dependency_trigger_key_is_null_when_multiple_triggers_share_it(pg_url: str) -> None:
    user_id, org_id = _create_tenant(pg_url)

    async def exercise() -> None:
        engine = create_async_engine(pg_url)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with factory() as session:
                request, _ = await _publish_fixture(
                    session,
                    org_id=org_id,
                    user_id=user_id,
                    duplicate_child_trigger=True,
                )
                bundle = await DefinitionCommandService(session).compile_definition_bundle(
                    org_id=org_id,
                    request=request,
                )
                trigger_key = await session.scalar(
                    text(
                        "SELECT trigger_key FROM definition_bundle_dependency "
                        "WHERE org_id = :org_id AND parent_bundle_id = :bundle_id"
                    ),
                    {"org_id": org_id, "bundle_id": bundle.id},
                )
                assert trigger_key is None
                await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(exercise())


def test_concurrent_same_checksum_returns_one_bundle_per_node(pg_url: str) -> None:
    user_id, org_id = _create_tenant(pg_url)

    async def exercise() -> None:
        engine = create_async_engine(pg_url)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with factory() as session:
                request, _ = await _publish_fixture(
                    session,
                    org_id=org_id,
                    user_id=user_id,
                )
                await session.commit()

            async def compile_once() -> uuid.UUID:
                async with factory() as session:
                    bundle = await DefinitionCommandService(session).compile_definition_bundle(
                        org_id=org_id,
                        request=request,
                    )
                    bundle_id = bundle.id
                    await session.commit()
                    return bundle_id

            first_id, second_id = await asyncio.gather(compile_once(), compile_once())
            assert first_id == second_id

            async with factory() as session:
                bundles = list(
                    (
                        await session.scalars(
                            text(
                                "SELECT id FROM definition_bundle "
                                "WHERE org_id = :org_id ORDER BY id"
                            ),
                            {"org_id": org_id},
                        )
                    ).all()
                )
                assert len(bundles) == 2
        finally:
            await engine.dispose()

    asyncio.run(exercise())


def test_repository_mutations_are_not_public_application_api() -> None:
    from polis.modules.kernel import repository

    forbidden = {
        "add_bundle_snapshot",
        "create_definition_draft",
        "deprecate_definition",
        "publish_definition",
        "update_definition_draft",
    }
    assert forbidden.isdisjoint(repository.__all__)
    assert DefinitionCommandService.compile_definition_bundle is not None
    assert DefinitionBundle.__tablename__ == "definition_bundle"
