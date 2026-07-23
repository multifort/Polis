"""K1-T3 deterministic Definition Compiler contracts."""

from __future__ import annotations

import inspect
import json
import uuid
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest

from polis.modules.kernel.application import definition_compiler as compiler_module
from polis.modules.kernel.application.definition_compiler import (
    MAX_DEPENDENCY_DEPTH,
    MAX_DEPENDENCY_NODES,
    CompileBundleRequest,
    CompiledBundleReference,
    DefinitionCatalog,
    DefinitionCompiler,
    DefinitionVersionSnapshot,
)
from polis.modules.kernel.errors import KernelProtocolError
from polis.modules.kernel.schemas import DEFINITION_V1_ADAPTER, definition_checksum

FIXTURE_PATH = (
    Path(__file__).parents[3]
    / "docs"
    / "design"
    / "v3"
    / "kernel"
    / "fixtures"
    / "generic-definition-set-v1.json"
)
ORG_ID = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
OTHER_ORG_ID = uuid.UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")


def _fixture() -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(FIXTURE_PATH.read_text()))


def _version_id(kind: str, key: str, suffix: str = "1") -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, f"polis:test:{kind}:{key}:{suffix}")


def _snapshot(
    definition: dict[str, Any],
    *,
    owner_org_id: uuid.UUID | None = ORG_ID,
    status: str = "published",
    suffix: str = "1",
) -> DefinitionVersionSnapshot:
    parsed = DEFINITION_V1_ADAPTER.validate_python(definition)
    kind = cast(str, parsed.definition_kind)
    return DefinitionVersionSnapshot(
        id=_version_id(kind, parsed.key, suffix),
        kind=cast(Any, kind),
        owner_org_id=owner_org_id,
        key=parsed.key,
        version="1.0.0",
        visibility="private" if owner_org_id is not None else "public",
        status=cast(Any, status),
        checksum=definition_checksum(parsed),
        definition=parsed.model_dump(mode="json", by_alias=True),
    )


def _fixture_catalog() -> tuple[DefinitionCatalog, dict[str, DefinitionVersionSnapshot]]:
    fixture = _fixture()
    snapshots = {
        "domain": _snapshot(fixture["domain_package"]),
        **{role["key"]: _snapshot(role) for role in fixture["roles"]},
        **{work["key"]: _snapshot(work) for work in fixture["works"]},
    }
    return (
        DefinitionCatalog(
            domain_packages={snapshots["domain"].id: snapshots["domain"]},
            works={
                snapshot.id: snapshot
                for key, snapshot in snapshots.items()
                if key.startswith("core.") and snapshot.kind == "work"
            },
            roles={
                snapshot.id: snapshot
                for key, snapshot in snapshots.items()
                if key.startswith("core.") and snapshot.kind == "role"
            },
        ),
        snapshots,
    )


def _request_for(
    work: DefinitionVersionSnapshot,
    snapshots: dict[str, DefinitionVersionSnapshot],
    *,
    children: dict[str, CompileBundleRequest] | None = None,
) -> CompileBundleRequest:
    definition = cast(dict[str, Any], work.definition)
    return CompileBundleRequest(
        domain_package_version_id=snapshots["domain"].id,
        work_definition_version_id=work.id,
        role_versions_by_slot={
            slot["key"]: snapshots[slot["role_definition_key"]].id
            for slot in definition["role_slots"]
        },
        child_dependencies_by_key=children or {},
    )


def _assessment_request(
    snapshots: dict[str, DefinitionVersionSnapshot],
) -> CompileBundleRequest:
    remediation = _request_for(snapshots["core.remediation"], snapshots)
    return _request_for(
        snapshots["core.assessment"],
        snapshots,
        children={"remediation_v1": remediation},
    )


def test_fixture_closure_compiles_postorder_and_is_deterministic() -> None:
    catalog, snapshots = _fixture_catalog()
    compiler = DefinitionCompiler()

    first_plan = compiler.plan(
        org_id=ORG_ID,
        request=_assessment_request(snapshots),
        catalog=catalog,
    )
    second_plan = compiler.plan(
        org_id=ORG_ID,
        request=_assessment_request(snapshots),
        catalog=catalog,
    )

    assert [node.work.key for node in first_plan.postorder] == [
        "core.remediation",
        "core.assessment",
    ]
    assert first_plan == second_plan

    child = compiler.compile_node(first_plan.postorder[0], child_bundles_by_key={})
    child_reference = CompiledBundleReference(
        bundle_id=uuid.UUID("11111111-1111-4111-8111-111111111111"),
        checksum=child.checksum,
    )
    parent = compiler.compile_node(
        first_plan.root,
        child_bundles_by_key={"remediation_v1": child_reference},
    )
    repeated = compiler.compile_node(
        second_plan.root,
        child_bundles_by_key={"remediation_v1": child_reference},
    )

    assert parent == repeated
    assert parent.checksum == repeated.checksum
    assert parent.child_work_bundle_dependencies == {
        "remediation_v1": {
            "bundle_id": str(child_reference.bundle_id),
            "checksum": child.checksum,
            "work_definition_key": "core.remediation",
        }
    }
    assert parent.dependencies[0].dependency_key == "remediation_v1"
    assert parent.dependencies[0].trigger_key == "create_remediation_for_medium_score"
    assert [role.role_slot_key for role in parent.roles] == ["owner", "worker"]


def test_any_fixed_version_input_change_changes_bundle_checksum() -> None:
    catalog, snapshots = _fixture_catalog()
    compiler = DefinitionCompiler()
    request = _request_for(snapshots["core.remediation"], snapshots)
    original = compiler.compile_node(
        compiler.plan(org_id=ORG_ID, request=request, catalog=catalog).root,
        child_bundles_by_key={},
    )

    replacement_role = replace(
        snapshots["core.worker"],
        id=_version_id("role", "core.worker", "2"),
        version="1.0.1",
    )
    changed_catalog = replace(
        catalog,
        roles={**catalog.roles, replacement_role.id: replacement_role},
    )
    changed_request = request.model_copy(
        update={
            "role_versions_by_slot": {
                **request.role_versions_by_slot,
                "worker": replacement_role.id,
            }
        }
    )
    changed = compiler.compile_node(
        compiler.plan(
            org_id=ORG_ID,
            request=changed_request,
            catalog=changed_catalog,
        ).root,
        child_bundles_by_key={},
    )

    assert changed.checksum != original.checksum


@pytest.mark.parametrize("missing_slot", ["owner", "worker"])
def test_role_slot_key_set_must_match_exactly(missing_slot: str) -> None:
    catalog, snapshots = _fixture_catalog()
    request = _request_for(snapshots["core.remediation"], snapshots)
    roles = dict(request.role_versions_by_slot)
    roles.pop(missing_slot)

    with pytest.raises(KernelProtocolError) as caught:
        DefinitionCompiler().plan(
            org_id=ORG_ID,
            request=request.model_copy(update={"role_versions_by_slot": roles}),
            catalog=catalog,
        )

    assert caught.value.code == "BUNDLE_INCOMPATIBLE"
    assert caught.value.path == "/role_versions_by_slot"


def test_role_key_must_match_slot_declaration() -> None:
    catalog, snapshots = _fixture_catalog()
    request = _request_for(snapshots["core.remediation"], snapshots)
    swapped = {
        "owner": snapshots["core.worker"].id,
        "worker": snapshots["core.owner"].id,
    }

    with pytest.raises(KernelProtocolError, match="slot expects role") as caught:
        DefinitionCompiler().plan(
            org_id=ORG_ID,
            request=request.model_copy(update={"role_versions_by_slot": swapped}),
            catalog=catalog,
        )

    assert caught.value.code == "BUNDLE_INCOMPATIBLE"


@pytest.mark.parametrize("status", ["draft", "deprecated"])
def test_only_published_versions_can_create_new_bundles(status: str) -> None:
    catalog, snapshots = _fixture_catalog()
    work = replace(snapshots["core.remediation"], status=cast(Any, status))
    changed = replace(
        catalog,
        works={
            work.id: work,
            snapshots["core.assessment"].id: snapshots["core.assessment"],
        },
    )

    with pytest.raises(KernelProtocolError) as caught:
        DefinitionCompiler().plan(
            org_id=ORG_ID,
            request=_request_for(work, snapshots),
            catalog=changed,
        )

    assert caught.value.code == "DEFINITION_NOT_PUBLISHED"


def test_other_organization_private_version_is_hidden() -> None:
    catalog, snapshots = _fixture_catalog()
    work = replace(snapshots["core.remediation"], owner_org_id=OTHER_ORG_ID)
    changed = replace(catalog, works={work.id: work})

    with pytest.raises(KernelProtocolError) as caught:
        DefinitionCompiler().plan(
            org_id=ORG_ID,
            request=_request_for(work, snapshots),
            catalog=changed,
        )

    assert caught.value.code == "DEFINITION_NOT_FOUND"


@pytest.mark.parametrize(
    ("children", "expected_fragment"),
    [
        ({}, "missing=['remediation_v1']"),
        (
            {
                "remediation_v1": "valid",
                "unexpected": "valid",
            },
            "extra=['unexpected']",
        ),
    ],
)
def test_child_dependency_key_set_must_match_exactly(
    children: dict[str, str],
    expected_fragment: str,
) -> None:
    catalog, snapshots = _fixture_catalog()
    valid_child = _request_for(snapshots["core.remediation"], snapshots)
    resolved_children = {key: valid_child for key in children}
    request = _request_for(
        snapshots["core.assessment"],
        snapshots,
        children=resolved_children,
    )

    with pytest.raises(KernelProtocolError) as caught:
        DefinitionCompiler().plan(org_id=ORG_ID, request=request, catalog=catalog)

    assert caught.value.code == "BUNDLE_INCOMPATIBLE"
    assert caught.value.path == "/child_dependencies_by_key"
    assert expected_fragment in str(caught.value)


def test_child_work_key_must_match_dependency_declaration() -> None:
    fixture = _fixture()
    other_json = fixture["works"][0]
    other_json["key"] = "core.other"
    other = _snapshot(other_json)
    fixture["domain_package"]["compatible_work_definition_keys"].append("core.other")
    domain = _snapshot(fixture["domain_package"])
    catalog, snapshots = _fixture_catalog()
    catalog = replace(
        catalog,
        domain_packages={domain.id: domain},
        works={**catalog.works, other.id: other},
    )
    snapshots["domain"] = domain
    snapshots["core.other"] = other
    wrong_child = _request_for(other, snapshots)
    request = _request_for(
        snapshots["core.assessment"],
        snapshots,
        children={"remediation_v1": wrong_child},
    )

    with pytest.raises(KernelProtocolError, match="dependency expects work") as caught:
        DefinitionCompiler().plan(org_id=ORG_ID, request=request, catalog=catalog)

    assert caught.value.code == "BUNDLE_INCOMPATIBLE"
    assert caught.value.path.endswith(
        "/child_dependencies_by_key/remediation_v1/work_definition_version_id"
    )


def test_dependency_cycle_reports_complete_dependency_path() -> None:
    catalog, snapshots = _fixture_catalog()
    cyclic_child = _request_for(snapshots["core.assessment"], snapshots)
    request = _request_for(
        snapshots["core.assessment"],
        snapshots,
        children={"remediation_v1": cyclic_child},
    )

    with pytest.raises(KernelProtocolError, match="dependency cycle") as caught:
        DefinitionCompiler().plan(org_id=ORG_ID, request=request, catalog=catalog)

    assert caught.value.code == "BUNDLE_DEPENDENCY_CYCLE"
    assert caught.value.path == "/child_dependencies_by_key/remediation_v1"


def _chain_fixture(
    depth: int,
) -> tuple[
    DefinitionCatalog,
    dict[str, DefinitionVersionSnapshot],
    CompileBundleRequest,
]:
    fixture = _fixture()
    roles = {role["key"]: _snapshot(role) for role in fixture["roles"]}
    domain_json = fixture["domain_package"]
    works: list[DefinitionVersionSnapshot] = []
    child_trigger = next(
        trigger
        for trigger in fixture["works"][1]["triggers"]
        if trigger["emit_command"]["command_type"] == "create_child_work"
    )
    for index in range(depth + 1):
        work_json = json.loads(json.dumps(fixture["works"][0]))
        work_json["key"] = f"core.chain_{index}"
        if index < depth:
            work_json["child_dependencies"] = [
                {
                    "dependency_key": "next",
                    "work_definition_key": f"core.chain_{index + 1}",
                    "allowed_scope_types": ["work_group"],
                }
            ]
            trigger = json.loads(json.dumps(child_trigger))
            trigger["key"] = "create_next"
            trigger["emit_command"]["child_bundle_dependency_key"] = "next"
            work_json["triggers"].append(trigger)
        else:
            work_json["child_dependencies"] = []
        works.append(_snapshot(work_json))
    domain_json["compatible_work_definition_keys"] = [work.key for work in works]
    domain = _snapshot(domain_json)
    snapshots = {
        "domain": domain,
        **roles,
        **{work.key: work for work in works},
    }
    catalog = DefinitionCatalog(
        domain_packages={domain.id: domain},
        works={work.id: work for work in works},
        roles={role.id: role for role in roles.values()},
    )
    request: CompileBundleRequest | None = None
    for work in reversed(works):
        request = _request_for(
            work,
            snapshots,
            children={} if request is None else {"next": request},
        )
    assert request is not None
    return catalog, snapshots, request


def test_dependency_depth_boundary_passes_and_overflow_has_path() -> None:
    catalog, _, at_limit = _chain_fixture(MAX_DEPENDENCY_DEPTH)
    plan = DefinitionCompiler().plan(org_id=ORG_ID, request=at_limit, catalog=catalog)
    assert len(plan.postorder) == MAX_DEPENDENCY_DEPTH + 1

    over_catalog, _, over_limit = _chain_fixture(MAX_DEPENDENCY_DEPTH + 1)
    with pytest.raises(KernelProtocolError) as caught:
        DefinitionCompiler().plan(
            org_id=ORG_ID,
            request=over_limit,
            catalog=over_catalog,
        )
    assert caught.value.code == "BUNDLE_DEPENDENCY_LIMIT_EXCEEDED"
    assert caught.value.path.count("/child_dependencies_by_key/next") == (MAX_DEPENDENCY_DEPTH + 1)


def _wide_fixture(
    child_count: int,
) -> tuple[DefinitionCatalog, dict[str, DefinitionVersionSnapshot], CompileBundleRequest]:
    fixture = _fixture()
    root_json = json.loads(json.dumps(fixture["works"][1]))
    child_template = next(
        trigger
        for trigger in root_json["triggers"]
        if trigger["emit_command"]["command_type"] == "create_child_work"
    )
    root_json["key"] = "core.wide"
    root_json["child_dependencies"] = []
    root_json["triggers"] = [
        trigger
        for trigger in root_json["triggers"]
        if trigger["emit_command"]["command_type"] != "create_child_work"
    ]
    for index in range(child_count):
        dependency_key = f"child_{index}"
        root_json["child_dependencies"].append(
            {
                "dependency_key": dependency_key,
                "work_definition_key": "core.remediation",
                "allowed_scope_types": ["work_group"],
            }
        )
        trigger = json.loads(json.dumps(child_template))
        trigger["key"] = f"create_child_{index}"
        trigger["emit_command"]["child_bundle_dependency_key"] = dependency_key
        root_json["triggers"].append(trigger)
    domain_json = fixture["domain_package"]
    domain_json["compatible_work_definition_keys"].append("core.wide")
    snapshots = {
        "domain": _snapshot(domain_json),
        **{role["key"]: _snapshot(role) for role in fixture["roles"]},
        "core.remediation": _snapshot(fixture["works"][0]),
        "core.wide": _snapshot(root_json),
    }
    catalog = DefinitionCatalog(
        domain_packages={snapshots["domain"].id: snapshots["domain"]},
        works={
            snapshots["core.remediation"].id: snapshots["core.remediation"],
            snapshots["core.wide"].id: snapshots["core.wide"],
        },
        roles={
            snapshots["core.owner"].id: snapshots["core.owner"],
            snapshots["core.worker"].id: snapshots["core.worker"],
        },
    )
    child_request = _request_for(snapshots["core.remediation"], snapshots)
    request = _request_for(
        snapshots["core.wide"],
        snapshots,
        children={f"child_{index}": child_request for index in range(child_count)},
    )
    return catalog, snapshots, request


def test_dependency_node_boundary_is_deterministic() -> None:
    at_limit_catalog, _, at_limit = _wide_fixture(MAX_DEPENDENCY_NODES - 1)
    assert (
        len(
            DefinitionCompiler()
            .plan(org_id=ORG_ID, request=at_limit, catalog=at_limit_catalog)
            .postorder
        )
        == MAX_DEPENDENCY_NODES
    )

    over_catalog, _, over_limit = _wide_fixture(MAX_DEPENDENCY_NODES)
    with pytest.raises(KernelProtocolError) as caught:
        DefinitionCompiler().plan(
            org_id=ORG_ID,
            request=over_limit,
            catalog=over_catalog,
        )
    assert caught.value.code == "BUNDLE_DEPENDENCY_LIMIT_EXCEEDED"


def test_unreachable_state_and_direct_trigger_cycle_are_rejected() -> None:
    fixture = _fixture()
    work_json = fixture["works"][0]
    work_json["state_machine"]["states"].append(
        {"key": "orphaned", "terminal": False, "category": "open"}
    )
    unreachable = _snapshot(work_json)
    catalog, snapshots = _fixture_catalog()
    catalog = replace(catalog, works={unreachable.id: unreachable})
    snapshots["core.remediation"] = unreachable
    with pytest.raises(KernelProtocolError, match="unreachable states") as caught:
        DefinitionCompiler().plan(
            org_id=ORG_ID,
            request=_request_for(unreachable, snapshots),
            catalog=catalog,
        )
    assert caught.value.code == "BUNDLE_INCOMPATIBLE"

    fixture = _fixture()
    work_json = fixture["works"][0]
    complete_transition = next(
        transition
        for transition in work_json["state_machine"]["transitions"]
        if transition["command_type"] == "complete_work"
    )
    complete_event = complete_transition["effects"][0]["event_type"]
    complete_trigger = next(
        trigger
        for trigger in work_json["triggers"]
        if trigger["emit_command"]["command_type"] == "complete_work"
    )
    complete_trigger["on_event"] = complete_event
    cyclic = _snapshot(work_json)
    catalog, snapshots = _fixture_catalog()
    catalog = replace(catalog, works={cyclic.id: cyclic})
    snapshots["core.remediation"] = cyclic
    with pytest.raises(KernelProtocolError, match="direct cycle") as caught:
        DefinitionCompiler().plan(
            org_id=ORG_ID,
            request=_request_for(cyclic, snapshots),
            catalog=catalog,
        )
    assert caught.value.code == "BUNDLE_INCOMPATIBLE"


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        (
            "collaboration",
            {"receives_from": ["ghost"], "hands_off_to": [], "escalates_to": []},
            "unknown slots",
        ),
        ("quality_bar", {"evaluation_rule_keys": ["ghost"]}, "unknown evaluation rules"),
    ],
)
def test_role_cross_definition_references_are_checked(
    field: str,
    value: dict[str, Any],
    message: str,
) -> None:
    fixture = _fixture()
    worker_json = fixture["roles"][1]
    worker_json[field] = value
    worker = _snapshot(worker_json)
    catalog, snapshots = _fixture_catalog()
    catalog = replace(
        catalog,
        roles={**catalog.roles, worker.id: worker},
    )
    snapshots["core.worker"] = worker

    with pytest.raises(KernelProtocolError, match=message) as caught:
        DefinitionCompiler().plan(
            org_id=ORG_ID,
            request=_request_for(snapshots["core.remediation"], snapshots),
            catalog=catalog,
        )

    assert caught.value.code == "BUNDLE_INCOMPATIBLE"


def test_compiler_is_persistence_neutral() -> None:
    source = inspect.getsource(compiler_module)
    compiler = DefinitionCompiler()

    assert "sqlalchemy" not in source
    assert "AsyncSession" not in source
    assert ".commit(" not in source
    assert not hasattr(compiler, "session")
