"""Pure, deterministic compiler for immutable V3 Definition bundles.

The compiler owns no database session and performs no persistence.  A command
service resolves and locks version rows, passes immutable snapshots here, then
persists the returned drafts from children to parents.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints

from polis.modules.kernel.domain.canonical import canonical_checksum
from polis.modules.kernel.errors import KernelProtocolError
from polis.modules.kernel.schemas import (
    DEFINITION_V1_ADAPTER,
    DomainPackageDefinitionV1,
    EmitEventEffectV1,
    RoleDefinitionV1,
    WorkDefinitionV1,
    definition_checksum,
)

COMPILER_VERSION = "1.0.0"
KERNEL_CONTRACT_VERSION = "3.4"
MIN_KERNEL_VERSION = "3.4.0"
MAX_DEPENDENCY_DEPTH = 16
MAX_DEPENDENCY_NODES = 128

type DefinitionKind = Literal["domain_package", "work", "role"]
type DefinitionStatus = Literal["draft", "published", "deprecated"]
type DefinitionVisibility = Literal["public", "private"]

LocalKey = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]*$")]


class CompileBundleRequest(BaseModel):
    """Recursive, exact-version payload accepted by bundle compilation."""

    model_config = ConfigDict(extra="forbid", strict=True)

    domain_package_version_id: uuid.UUID
    work_definition_version_id: uuid.UUID
    role_versions_by_slot: dict[LocalKey, uuid.UUID]
    child_dependencies_by_key: dict[LocalKey, CompileBundleRequest]


CompileBundleRequest.model_rebuild()


@dataclass(frozen=True, slots=True)
class DefinitionVersionSnapshot:
    """Immutable projection of one locked Definition version row."""

    id: uuid.UUID
    kind: DefinitionKind
    owner_org_id: uuid.UUID | None
    key: str
    version: str
    visibility: DefinitionVisibility
    status: DefinitionStatus
    checksum: str
    definition: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class DefinitionCatalog:
    """All version snapshots collected for one compile command."""

    domain_packages: Mapping[uuid.UUID, DefinitionVersionSnapshot]
    works: Mapping[uuid.UUID, DefinitionVersionSnapshot]
    roles: Mapping[uuid.UUID, DefinitionVersionSnapshot]

    def get(
        self,
        kind: DefinitionKind,
        version_id: uuid.UUID,
        *,
        path: str,
    ) -> DefinitionVersionSnapshot:
        collections: Mapping[DefinitionKind, Mapping[uuid.UUID, DefinitionVersionSnapshot]] = {
            "domain_package": self.domain_packages,
            "work": self.works,
            "role": self.roles,
        }
        snapshot = collections[kind].get(version_id)
        if snapshot is None:
            raise KernelProtocolError(
                "DEFINITION_NOT_FOUND",
                path,
                f"{kind} definition version '{version_id}' was not found",
            )
        if snapshot.kind != kind:
            raise KernelProtocolError(
                "BUNDLE_INCOMPATIBLE",
                path,
                f"expected {kind} definition version, got {snapshot.kind}",
            )
        return snapshot


@dataclass(frozen=True, slots=True)
class ResolvedRole:
    slot_key: str
    snapshot: DefinitionVersionSnapshot
    definition: RoleDefinitionV1


@dataclass(frozen=True, slots=True)
class ResolvedBundleNode:
    """One validated node in a post-order compilation plan."""

    path: tuple[str, ...]
    domain_snapshot: DefinitionVersionSnapshot
    domain: DomainPackageDefinitionV1
    work_snapshot: DefinitionVersionSnapshot
    work: WorkDefinitionV1
    roles: tuple[ResolvedRole, ...]
    children: tuple[tuple[str, ResolvedBundleNode], ...]

    @property
    def identity(self) -> tuple[uuid.UUID, uuid.UUID]:
        return self.domain_snapshot.id, self.work_snapshot.id


@dataclass(frozen=True, slots=True)
class CompilationPlan:
    """Validated dependency closure ordered children before parents."""

    root: ResolvedBundleNode
    postorder: tuple[ResolvedBundleNode, ...]


@dataclass(frozen=True, slots=True)
class CompiledBundleReference:
    bundle_id: uuid.UUID
    checksum: str


@dataclass(frozen=True, slots=True)
class CompiledRoleLink:
    role_slot_key: str
    role_definition_version_id: uuid.UUID


@dataclass(frozen=True, slots=True)
class CompiledDependencyLink:
    dependency_key: str
    trigger_key: str | None
    child_bundle_id: uuid.UUID
    child_bundle_checksum: str


@dataclass(frozen=True, slots=True)
class CompiledBundleDraft:
    """Persistence-neutral immutable bundle value."""

    domain_package_version_id: uuid.UUID
    work_definition_version_id: uuid.UUID
    compiled_definition: dict[str, Any]
    checksum: str
    compiler_version: str
    kernel_contract_version: str
    min_kernel_version: str
    child_work_bundle_dependencies: dict[str, dict[str, str]]
    roles: tuple[CompiledRoleLink, ...]
    dependencies: tuple[CompiledDependencyLink, ...]


def _pointer_token(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _dependency_path(path: tuple[str, ...]) -> str:
    result = ""
    for key in path:
        result += f"/child_dependencies_by_key/{_pointer_token(key)}"
    return result


class DefinitionCompiler:
    """Validate dependency closures and compile resolved nodes deterministically."""

    def collect_version_ids(
        self,
        request: CompileBundleRequest,
    ) -> dict[DefinitionKind, set[uuid.UUID]]:
        """Validate structural closure limits before I/O and collect exact row IDs."""

        collected: dict[DefinitionKind, set[uuid.UUID]] = {
            "domain_package": set(),
            "work": set(),
            "role": set(),
        }
        visiting: list[tuple[uuid.UUID, uuid.UUID]] = []
        visiting_paths: list[tuple[str, ...]] = []
        node_count = 0

        def visit(current: CompileBundleRequest, path: tuple[str, ...]) -> None:
            nonlocal node_count
            if len(path) > MAX_DEPENDENCY_DEPTH:
                raise KernelProtocolError(
                    "BUNDLE_DEPENDENCY_LIMIT_EXCEEDED",
                    _dependency_path(path),
                    f"dependency depth exceeds {MAX_DEPENDENCY_DEPTH}",
                )
            node_count += 1
            if node_count > MAX_DEPENDENCY_NODES:
                raise KernelProtocolError(
                    "BUNDLE_DEPENDENCY_LIMIT_EXCEEDED",
                    _dependency_path(path),
                    f"dependency closure exceeds {MAX_DEPENDENCY_NODES} nodes",
                )
            identity = (
                current.domain_package_version_id,
                current.work_definition_version_id,
            )
            if identity in visiting:
                start = visiting.index(identity)
                cycle_path = [*visiting_paths[start:], path]
                rendered = " -> ".join(_dependency_path(item) or "/" for item in cycle_path)
                raise KernelProtocolError(
                    "BUNDLE_DEPENDENCY_CYCLE",
                    _dependency_path(path),
                    f"dependency cycle detected: {rendered}",
                )
            collected["domain_package"].add(current.domain_package_version_id)
            collected["work"].add(current.work_definition_version_id)
            collected["role"].update(current.role_versions_by_slot.values())
            visiting.append(identity)
            visiting_paths.append(path)
            for key in sorted(current.child_dependencies_by_key):
                visit(current.child_dependencies_by_key[key], (*path, key))
            visiting.pop()
            visiting_paths.pop()

        visit(request, ())
        return collected

    def plan(
        self,
        *,
        org_id: uuid.UUID,
        request: CompileBundleRequest,
        catalog: DefinitionCatalog,
    ) -> CompilationPlan:
        postorder: list[ResolvedBundleNode] = []
        visiting: list[tuple[uuid.UUID, uuid.UUID]] = []
        visiting_paths: list[tuple[str, ...]] = []
        node_count = 0

        def visit(
            current: CompileBundleRequest,
            *,
            path: tuple[str, ...],
        ) -> ResolvedBundleNode:
            nonlocal node_count
            depth = len(path)
            if depth > MAX_DEPENDENCY_DEPTH:
                raise KernelProtocolError(
                    "BUNDLE_DEPENDENCY_LIMIT_EXCEEDED",
                    _dependency_path(path),
                    f"dependency depth exceeds {MAX_DEPENDENCY_DEPTH}",
                )
            node_count += 1
            if node_count > MAX_DEPENDENCY_NODES:
                raise KernelProtocolError(
                    "BUNDLE_DEPENDENCY_LIMIT_EXCEEDED",
                    _dependency_path(path),
                    f"dependency closure exceeds {MAX_DEPENDENCY_NODES} nodes",
                )

            base_path = _dependency_path(path)
            domain_snapshot = catalog.get(
                "domain_package",
                current.domain_package_version_id,
                path=f"{base_path}/domain_package_version_id",
            )
            work_snapshot = catalog.get(
                "work",
                current.work_definition_version_id,
                path=f"{base_path}/work_definition_version_id",
            )
            identity = (domain_snapshot.id, work_snapshot.id)
            if identity in visiting:
                start = visiting.index(identity)
                cycle_path = [*visiting_paths[start:], path]
                rendered = " -> ".join(_dependency_path(item) or "/" for item in cycle_path)
                raise KernelProtocolError(
                    "BUNDLE_DEPENDENCY_CYCLE",
                    base_path,
                    f"dependency cycle detected: {rendered}",
                )

            domain = self._parse_snapshot(
                domain_snapshot,
                org_id=org_id,
                expected_type=DomainPackageDefinitionV1,
                path=f"{base_path}/domain_package_version_id",
            )
            work = self._parse_snapshot(
                work_snapshot,
                org_id=org_id,
                expected_type=WorkDefinitionV1,
                path=f"{base_path}/work_definition_version_id",
            )
            self._validate_domain_work(domain, work, path=base_path)
            roles = self._resolve_roles(
                org_id=org_id,
                request=current,
                catalog=catalog,
                domain=domain,
                work=work,
                path=base_path,
            )
            self._validate_static_work(work, roles=roles, path=base_path)

            expected_dependencies = {item.dependency_key: item for item in work.child_dependencies}
            self._require_exact_keys(
                expected=set(expected_dependencies),
                actual=set(current.child_dependencies_by_key),
                path=f"{base_path}/child_dependencies_by_key",
                noun="child dependency",
            )

            visiting.append(identity)
            visiting_paths.append(path)
            children: list[tuple[str, ResolvedBundleNode]] = []
            for dependency_key in sorted(expected_dependencies):
                child_request = current.child_dependencies_by_key[dependency_key]
                child = visit(child_request, path=(*path, dependency_key))
                declaration = expected_dependencies[dependency_key]
                self._validate_child(
                    domain=domain,
                    declaration_work_key=declaration.work_definition_key,
                    allowed_scope_types=set(declaration.allowed_scope_types),
                    child=child,
                    path=f"{base_path}/child_dependencies_by_key/{_pointer_token(dependency_key)}",
                )
                children.append((dependency_key, child))
            visiting.pop()
            visiting_paths.pop()

            node = ResolvedBundleNode(
                path=path,
                domain_snapshot=domain_snapshot,
                domain=domain,
                work_snapshot=work_snapshot,
                work=work,
                roles=roles,
                children=tuple(children),
            )
            postorder.append(node)
            return node

        root = visit(request, path=())
        return CompilationPlan(root=root, postorder=tuple(postorder))

    def compile_node(
        self,
        node: ResolvedBundleNode,
        *,
        child_bundles_by_key: Mapping[str, CompiledBundleReference],
    ) -> CompiledBundleDraft:
        expected = {key for key, _ in node.children}
        self._require_exact_keys(
            expected=expected,
            actual=set(child_bundles_by_key),
            path="/child_bundles_by_key",
            noun="compiled child bundle",
        )

        trigger_keys_by_dependency: dict[str, list[str]] = {key: [] for key in expected}
        for trigger in node.work.triggers:
            dependency_key = trigger.emit_command.child_bundle_dependency_key
            if dependency_key is not None:
                trigger_keys_by_dependency[dependency_key].append(trigger.key)

        child_projection: dict[str, dict[str, str]] = {}
        dependency_links: list[CompiledDependencyLink] = []
        for dependency_key, child in node.children:
            reference = child_bundles_by_key[dependency_key]
            child_projection[dependency_key] = {
                "bundle_id": str(reference.bundle_id),
                "checksum": reference.checksum,
                "work_definition_key": child.work.key,
            }
            trigger_keys = sorted(trigger_keys_by_dependency[dependency_key])
            dependency_links.append(
                CompiledDependencyLink(
                    dependency_key=dependency_key,
                    trigger_key=trigger_keys[0] if len(trigger_keys) == 1 else None,
                    child_bundle_id=reference.bundle_id,
                    child_bundle_checksum=reference.checksum,
                )
            )

        roles_projection = {
            role.slot_key: {
                "role_definition_version_id": str(role.snapshot.id),
                "version": role.snapshot.version,
                "checksum": role.snapshot.checksum,
                "definition": role.definition.model_dump(mode="json", by_alias=True),
            }
            for role in node.roles
        }
        compiled_definition: dict[str, Any] = {
            "schema_version": 1,
            "domain_package": {
                "domain_package_version_id": str(node.domain_snapshot.id),
                "version": node.domain_snapshot.version,
                "checksum": node.domain_snapshot.checksum,
                "definition": node.domain.model_dump(mode="json", by_alias=True),
            },
            "work_definition": {
                "work_definition_version_id": str(node.work_snapshot.id),
                "version": node.work_snapshot.version,
                "checksum": node.work_snapshot.checksum,
                "definition": node.work.model_dump(mode="json", by_alias=True),
            },
            "roles_by_slot": roles_projection,
            "child_dependencies_by_key": child_projection,
        }
        checksum = canonical_checksum(
            {
                "compiled_definition": compiled_definition,
                "compiler_version": COMPILER_VERSION,
                "kernel_contract_version": KERNEL_CONTRACT_VERSION,
                "min_kernel_version": MIN_KERNEL_VERSION,
            }
        )
        return CompiledBundleDraft(
            domain_package_version_id=node.domain_snapshot.id,
            work_definition_version_id=node.work_snapshot.id,
            compiled_definition=compiled_definition,
            checksum=checksum,
            compiler_version=COMPILER_VERSION,
            kernel_contract_version=KERNEL_CONTRACT_VERSION,
            min_kernel_version=MIN_KERNEL_VERSION,
            child_work_bundle_dependencies=child_projection,
            roles=tuple(
                CompiledRoleLink(
                    role_slot_key=role.slot_key,
                    role_definition_version_id=role.snapshot.id,
                )
                for role in node.roles
            ),
            dependencies=tuple(dependency_links),
        )

    @staticmethod
    def _parse_snapshot[
        DefinitionT: DomainPackageDefinitionV1 | WorkDefinitionV1 | RoleDefinitionV1
    ](
        snapshot: DefinitionVersionSnapshot,
        *,
        org_id: uuid.UUID,
        expected_type: type[DefinitionT],
        path: str,
    ) -> DefinitionT:
        if snapshot.status != "published":
            raise KernelProtocolError(
                "DEFINITION_NOT_PUBLISHED",
                path,
                f"definition '{snapshot.key}@{snapshot.version}' is {snapshot.status}",
            )
        visible = (snapshot.visibility == "private" and snapshot.owner_org_id == org_id) or (
            snapshot.visibility == "public" and snapshot.owner_org_id is None
        )
        if not visible:
            raise KernelProtocolError(
                "DEFINITION_NOT_FOUND",
                path,
                "definition version is not visible to this organization",
            )
        parsed = DEFINITION_V1_ADAPTER.validate_python(dict(snapshot.definition))
        if not isinstance(parsed, expected_type):
            raise KernelProtocolError(
                "BUNDLE_INCOMPATIBLE",
                path,
                f"definition '{snapshot.key}' has unexpected kind",
            )
        if parsed.key != snapshot.key:
            raise KernelProtocolError(
                "BUNDLE_INCOMPATIBLE",
                path,
                f"row key '{snapshot.key}' does not match definition key '{parsed.key}'",
            )
        actual_checksum = definition_checksum(parsed)
        if actual_checksum != snapshot.checksum:
            raise KernelProtocolError(
                "BUNDLE_INCOMPATIBLE",
                path,
                "definition checksum does not match the locked version row",
            )
        return parsed

    @staticmethod
    def _require_exact_keys(
        *,
        expected: set[str],
        actual: set[str],
        path: str,
        noun: str,
    ) -> None:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        if missing or extra:
            raise KernelProtocolError(
                "BUNDLE_INCOMPATIBLE",
                path,
                f"{noun} keys differ; missing={missing}, extra={extra}",
            )

    @staticmethod
    def _validate_domain_work(
        domain: DomainPackageDefinitionV1,
        work: WorkDefinitionV1,
        *,
        path: str,
    ) -> None:
        if work.key not in domain.compatible_work_definition_keys:
            raise KernelProtocolError(
                "BUNDLE_INCOMPATIBLE",
                f"{path}/work_definition_version_id",
                f"domain '{domain.key}' does not allow work '{work.key}'",
            )
        domain_scopes = {scope.key for scope in domain.scope_types}
        unsupported = sorted(set(work.supported_scope_types) - domain_scopes)
        if unsupported:
            raise KernelProtocolError(
                "BUNDLE_INCOMPATIBLE",
                f"{path}/work_definition_version_id",
                f"work references domain-unknown scope types {unsupported}",
            )

    def _resolve_roles(
        self,
        *,
        org_id: uuid.UUID,
        request: CompileBundleRequest,
        catalog: DefinitionCatalog,
        domain: DomainPackageDefinitionV1,
        work: WorkDefinitionV1,
        path: str,
    ) -> tuple[ResolvedRole, ...]:
        slots = {slot.key: slot for slot in work.role_slots}
        self._require_exact_keys(
            expected=set(slots),
            actual=set(request.role_versions_by_slot),
            path=f"{path}/role_versions_by_slot",
            noun="role slot",
        )
        roles: list[ResolvedRole] = []
        for slot_key in sorted(slots):
            snapshot = catalog.get(
                "role",
                request.role_versions_by_slot[slot_key],
                path=f"{path}/role_versions_by_slot/{_pointer_token(slot_key)}",
            )
            role = self._parse_snapshot(
                snapshot,
                org_id=org_id,
                expected_type=RoleDefinitionV1,
                path=f"{path}/role_versions_by_slot/{_pointer_token(slot_key)}",
            )
            slot = slots[slot_key]
            if role.key != slot.role_definition_key:
                raise KernelProtocolError(
                    "BUNDLE_INCOMPATIBLE",
                    f"{path}/role_versions_by_slot/{_pointer_token(slot_key)}",
                    f"slot expects role '{slot.role_definition_key}', got '{role.key}'",
                )
            if role.key not in domain.compatible_role_definition_keys:
                raise KernelProtocolError(
                    "BUNDLE_INCOMPATIBLE",
                    f"{path}/role_versions_by_slot/{_pointer_token(slot_key)}",
                    f"domain '{domain.key}' does not allow role '{role.key}'",
                )
            roles.append(ResolvedRole(slot_key=slot_key, snapshot=snapshot, definition=role))
        return tuple(roles)

    @staticmethod
    def _validate_static_work(
        work: WorkDefinitionV1,
        *,
        roles: tuple[ResolvedRole, ...],
        path: str,
    ) -> None:
        reachable = {work.state_machine.initial_state}
        changed = True
        while changed:
            changed = False
            for transition in work.state_machine.transitions:
                if (
                    reachable.intersection(transition.from_states)
                    and transition.to not in reachable
                ):
                    reachable.add(transition.to)
                    changed = True
        state_keys = {state.key for state in work.state_machine.states}
        unreachable = sorted(state_keys - reachable)
        if unreachable:
            raise KernelProtocolError(
                "BUNDLE_INCOMPATIBLE",
                f"{path}/work_definition_version_id/definition/state_machine",
                f"state machine contains unreachable states {unreachable}",
            )

        slot_keys = {slot.key for slot in work.role_slots}
        evaluation_keys = {rule.key for rule in work.evaluation_rules}
        for role in roles:
            collaboration = role.definition.collaboration
            unknown_slots = (
                set(collaboration.receives_from)
                | set(collaboration.hands_off_to)
                | set(collaboration.escalates_to)
            ) - slot_keys
            if unknown_slots:
                raise KernelProtocolError(
                    "BUNDLE_INCOMPATIBLE",
                    f"{path}/role_versions_by_slot/{_pointer_token(role.slot_key)}",
                    f"role collaboration references unknown slots {sorted(unknown_slots)}",
                )
            unknown_rules = set(role.definition.quality_bar.evaluation_rule_keys) - evaluation_keys
            if unknown_rules:
                raise KernelProtocolError(
                    "BUNDLE_INCOMPATIBLE",
                    f"{path}/role_versions_by_slot/{_pointer_token(role.slot_key)}",
                    f"role quality bar references unknown evaluation rules {sorted(unknown_rules)}",
                )

        transitions_by_command = {
            transition.command_type: transition for transition in work.state_machine.transitions
        }
        for trigger in work.triggers:
            target_transition = transitions_by_command.get(trigger.emit_command.command_type)
            if target_transition is None:
                continue
            emitted_events = {
                effect.event_type
                for effect in target_transition.effects
                if isinstance(effect, EmitEventEffectV1)
            }
            if trigger.on_event in emitted_events:
                raise KernelProtocolError(
                    "BUNDLE_INCOMPATIBLE",
                    f"{path}/work_definition_version_id/definition/triggers/"
                    f"{_pointer_token(trigger.key)}",
                    f"trigger forms direct cycle {trigger.on_event} -> "
                    f"{trigger.emit_command.command_type} -> {trigger.on_event}",
                )

    @staticmethod
    def _validate_child(
        *,
        domain: DomainPackageDefinitionV1,
        declaration_work_key: str,
        allowed_scope_types: set[str],
        child: ResolvedBundleNode,
        path: str,
    ) -> None:
        if child.work.key != declaration_work_key:
            raise KernelProtocolError(
                "BUNDLE_INCOMPATIBLE",
                f"{path}/work_definition_version_id",
                f"dependency expects work '{declaration_work_key}', got '{child.work.key}'",
            )
        domain_scopes = {scope.key for scope in domain.scope_types}
        if not allowed_scope_types <= domain_scopes:
            raise KernelProtocolError(
                "BUNDLE_INCOMPATIBLE",
                path,
                "dependency allows scope types unknown to the domain",
            )
        child_domain_scopes = {scope.key for scope in child.domain.scope_types}
        if not allowed_scope_types <= child_domain_scopes:
            raise KernelProtocolError(
                "BUNDLE_INCOMPATIBLE",
                path,
                "dependency allows scope types unknown to the child domain",
            )
        if not allowed_scope_types <= set(child.work.supported_scope_types):
            raise KernelProtocolError(
                "BUNDLE_INCOMPATIBLE",
                path,
                "child work does not support every dependency scope type",
            )


__all__ = [
    "COMPILER_VERSION",
    "KERNEL_CONTRACT_VERSION",
    "MAX_DEPENDENCY_DEPTH",
    "MAX_DEPENDENCY_NODES",
    "MIN_KERNEL_VERSION",
    "CompilationPlan",
    "CompileBundleRequest",
    "CompiledBundleDraft",
    "CompiledBundleReference",
    "CompiledDependencyLink",
    "CompiledRoleLink",
    "DefinitionCatalog",
    "DefinitionCompiler",
    "DefinitionKind",
    "DefinitionVersionSnapshot",
    "ResolvedBundleNode",
    "ResolvedRole",
]
