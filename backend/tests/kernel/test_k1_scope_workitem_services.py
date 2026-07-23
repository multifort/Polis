"""K1 Gate: fixture definitions -> governance -> scope -> work -> responsibility."""

from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path
from typing import Any, cast

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from polis.modules.kernel.application.definition_commands import DefinitionCommandService
from polis.modules.kernel.application.definition_compiler import CompileBundleRequest
from polis.modules.kernel.application.scope_commands import ScopeCommandService
from polis.modules.kernel.application.work_items import WorkItemService
from polis.modules.kernel.errors import KernelProtocolError
from polis.modules.kernel.repository import DefinitionKind

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
FIXTURE_PATH = REPOSITORY_ROOT / "docs/design/v3/kernel/fixtures/generic-definition-set-v1.json"
GOVERNANCE_DOMAIN_ID = uuid.UUID("00000000-0000-4000-8000-000000000301")
GOVERNANCE_ROLE_ID = uuid.UUID("00000000-0000-4000-8000-000000000302")


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
                {"email": f"k1_gate_{uuid.uuid4().hex}@polis.dev"},
            ).scalar_one()
            org_id = connection.execute(
                text("INSERT INTO org (name, owner_user_id) VALUES (:name,:user) RETURNING id"),
                {"name": f"K1 Gate {uuid.uuid4().hex[:6]}", "user": user_id},
            ).scalar_one()
            connection.execute(
                text("INSERT INTO org_member (org_id,user_id,role) VALUES (:org,:user,'owner')"),
                {"org": org_id, "user": user_id},
            )
            return user_id, org_id
    finally:
        engine.dispose()


async def _publish_fixture_bundle(
    service: DefinitionCommandService,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    fixture = _fixture()
    definitions: list[tuple[DefinitionKind, dict[str, Any]]] = [
        ("domain_package", fixture["domain_package"]),
        *[("role", role) for role in fixture["roles"]],
        *[("work", work) for work in fixture["works"]],
    ]
    rows: dict[str, Any] = {}
    for kind, definition in definitions:
        row = await service.create_draft(
            kind=kind,
            owner_org_id=org_id,
            key=definition["key"],
            version="1.0.0",
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
    child_request = CompileBundleRequest(
        domain_package_version_id=rows["core.generic"].id,
        work_definition_version_id=rows["core.remediation"].id,
        role_versions_by_slot={
            "owner": rows["core.owner"].id,
            "worker": rows["core.worker"].id,
        },
        child_dependencies_by_key={},
    )
    bundle = await service.compile_definition_bundle(
        org_id=org_id,
        request=CompileBundleRequest(
            domain_package_version_id=rows["core.generic"].id,
            work_definition_version_id=rows["core.assessment"].id,
            role_versions_by_slot={
                "owner": rows["core.owner"].id,
                "worker": rows["core.worker"].id,
            },
            child_dependencies_by_key={"remediation_v1": child_request},
        ),
    )
    return rows["core.generic"].id, rows["core.owner"].id, bundle.id


def test_k1_fixture_closes_scope_work_and_responsibility_loop(pg_url: str) -> None:
    user_id, org_id = _create_tenant(pg_url)

    async def exercise() -> None:
        engine = create_async_engine(pg_url)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with factory() as session:
                scope_service = ScopeCommandService(session)
                governance = await scope_service.create_scope(
                    org_id=org_id,
                    actor_kind="human",
                    actor_ref=user_id,
                    domain_package_version_id=GOVERNANCE_DOMAIN_ID,
                    scope_type="org_governance",
                    display_name="Organization Governance",
                    attributes={
                        "kernel_policy": {
                            "schema_version": 1,
                            "max_concurrent_runs": 20,
                            "budget_limit_cents": 0,
                            "budget_enforcement": "observe",
                            "default_approval_ttl_seconds": 86_400,
                        }
                    },
                )
                governance_assignment = await scope_service.assign_scope_role(
                    org_id=org_id,
                    scope_id=governance.id,
                    actor_kind="human",
                    actor_ref=user_id,
                    role_definition_version_id=GOVERNANCE_ROLE_ID,
                    assignee_kind="human",
                    assignee_ref=user_id,
                    inheritance_mode="none",
                    authority_constraints={},
                )
                await scope_service.activate_scope_role(
                    org_id=org_id,
                    assignment_id=governance_assignment.id,
                    actor_kind="human",
                    actor_ref=user_id,
                    expected_version=1,
                )

                domain_id, owner_role_id, bundle_id = await _publish_fixture_bundle(
                    DefinitionCommandService(session),
                    org_id=org_id,
                    user_id=user_id,
                )
                work_service = WorkItemService(session)
                with pytest.raises(KernelProtocolError, match="WORK_SCOPE_TYPE_INVALID"):
                    await work_service.create_work_item(
                        org_id=org_id,
                        scope_id=governance.id,
                        definition_bundle_id=bundle_id,
                        title="Wrong scope",
                        inputs={
                            "subject_artifact_id": str(uuid.uuid4()),
                            "risk_level": "low",
                        },
                        created_by_kind="human",
                        created_by_ref=user_id,
                    )
                workspace = await scope_service.create_scope(
                    org_id=org_id,
                    actor_kind="human",
                    actor_ref=user_id,
                    domain_package_version_id=domain_id,
                    scope_type="workspace",
                    display_name="Workspace",
                    attributes={},
                )
                group = await scope_service.create_scope(
                    org_id=org_id,
                    actor_kind="human",
                    actor_ref=user_id,
                    domain_package_version_id=domain_id,
                    scope_type="work_group",
                    display_name="Remediation",
                    attributes={},
                    parent_scope_id=workspace.id,
                )
                dependency_group = await scope_service.create_scope(
                    org_id=org_id,
                    actor_kind="human",
                    actor_ref=user_id,
                    domain_package_version_id=domain_id,
                    scope_type="work_group",
                    display_name="Dependency",
                    attributes={},
                    parent_scope_id=workspace.id,
                )
                relation = await scope_service.relate_scopes(
                    org_id=org_id,
                    from_scope_id=group.id,
                    to_scope_id=dependency_group.id,
                    actor_kind="human",
                    actor_ref=user_id,
                    relationship_type="depends_on",
                    attributes={},
                )
                assert [
                    item.id
                    for item in await scope_service.list_scope_relations(
                        org_id=org_id, scope_id=group.id
                    )
                ] == [relation.id]
                owner_assignment = await scope_service.assign_scope_role(
                    org_id=org_id,
                    scope_id=group.id,
                    actor_kind="human",
                    actor_ref=user_id,
                    role_definition_version_id=owner_role_id,
                    assignee_kind="human",
                    assignee_ref=user_id,
                    inheritance_mode="none",
                    authority_constraints={"commands": ["start_work"]},
                )
                await scope_service.activate_scope_role(
                    org_id=org_id,
                    assignment_id=owner_assignment.id,
                    actor_kind="human",
                    actor_ref=user_id,
                    expected_version=1,
                )

                with pytest.raises(KernelProtocolError, match="SCHEMA_INSTANCE_INVALID"):
                    await work_service.create_work_item(
                        org_id=org_id,
                        scope_id=group.id,
                        definition_bundle_id=bundle_id,
                        title="Invalid",
                        inputs={},
                        created_by_kind="human",
                        created_by_ref=user_id,
                    )
                work = await work_service.create_work_item(
                    org_id=org_id,
                    scope_id=group.id,
                    definition_bundle_id=bundle_id,
                    title="Resolve finding",
                    inputs={
                        "subject_artifact_id": str(uuid.uuid4()),
                        "risk_level": "high",
                    },
                    created_by_kind="human",
                    created_by_ref=user_id,
                    priority=80,
                )
                binding = await work_service.bind_responsible_role(
                    org_id=org_id,
                    work_item_id=work.id,
                    role_slot_key="owner",
                    responsible_assignment_id=owner_assignment.id,
                )
                assert binding.responsibility_kind_snapshot == "accountable"
                stored_work = await work_service.get_work_item(org_id=org_id, work_item_id=work.id)
                assert stored_work.id == work.id
                assert {item.id for item in await scope_service.list_scopes(org_id=org_id)} == {
                    governance.id,
                    workspace.id,
                    group.id,
                    dependency_group.id,
                }
                with pytest.raises(KernelProtocolError, match="GOVERNANCE_SCOPE_ALREADY_EXISTS"):
                    await scope_service.create_scope(
                        org_id=org_id,
                        actor_kind="human",
                        actor_ref=user_id,
                        domain_package_version_id=GOVERNANCE_DOMAIN_ID,
                        scope_type="org_governance",
                        display_name="Organization Governance",
                        attributes=governance.attributes,
                    )
                _, changed = await scope_service.update_scope(
                    org_id=org_id,
                    scope_id=governance.id,
                    actor_kind="human",
                    actor_ref=user_id,
                    expected_version=governance.version,
                    display_name="Organization Governance",
                    attributes=governance.attributes,
                )
                assert changed is False

                governance_assignment.status = "suspended"
                await session.flush()
                with pytest.raises(KernelProtocolError, match="SCOPE_COMMAND_FORBIDDEN"):
                    await scope_service.create_scope(
                        org_id=org_id,
                        actor_kind="human",
                        actor_ref=user_id,
                        domain_package_version_id=domain_id,
                        scope_type="workspace",
                        display_name="Owner without assignment",
                        attributes={},
                    )
                await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(exercise())
