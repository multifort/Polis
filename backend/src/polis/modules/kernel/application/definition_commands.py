"""Definition-family write service for V3 kernel definitions and bundles."""

from __future__ import annotations

import uuid
from typing import Any, Literal, cast

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from polis.modules.kernel.application.definition_compiler import (
    CompileBundleRequest,
    CompiledBundleDraft,
    CompiledBundleReference,
    DefinitionCatalog,
    DefinitionCompiler,
    DefinitionKind,
    DefinitionVersionSnapshot,
)
from polis.modules.kernel.errors import KernelProtocolError
from polis.modules.kernel.models import (
    DefinitionBundle,
    DefinitionBundleDependency,
    DefinitionBundleRole,
)
from polis.modules.kernel.repository import (
    DefinitionVersion,
    _add_bundle_snapshot,
    _create_definition_draft,
    _deprecate_definition,
    _lock_visible_definition_versions,
    _publish_definition,
    _update_definition_draft,
    find_bundle_by_checksum,
)


class DefinitionCommandService:
    """The only application write surface for the Definition command family.

    The request dependency owns commit/rollback.  This service flushes within
    that transaction and the compiler remains persistence-neutral.
    """

    def __init__(
        self,
        session: AsyncSession,
        *,
        compiler: DefinitionCompiler | None = None,
    ) -> None:
        self._session = session
        self._compiler = compiler or DefinitionCompiler()

    async def create_draft(
        self,
        *,
        kind: DefinitionKind,
        owner_org_id: uuid.UUID | None,
        key: str,
        version: str,
        visibility: Literal["public", "private"],
        definition: dict[str, Any],
        created_by: uuid.UUID | None,
    ) -> DefinitionVersion:
        return await _create_definition_draft(
            self._session,
            kind=kind,
            owner_org_id=owner_org_id,
            key=key,
            version=version,
            visibility=visibility,
            definition=definition,
            created_by=created_by,
        )

    async def update_draft(
        self,
        *,
        kind: DefinitionKind,
        definition_id: uuid.UUID,
        owner_org_id: uuid.UUID | None,
        expected_revision: int,
        definition: dict[str, Any],
    ) -> DefinitionVersion:
        return await _update_definition_draft(
            self._session,
            kind=kind,
            definition_id=definition_id,
            owner_org_id=owner_org_id,
            expected_revision=expected_revision,
            definition=definition,
        )

    async def publish(
        self,
        *,
        kind: DefinitionKind,
        definition_id: uuid.UUID,
        owner_org_id: uuid.UUID | None,
        expected_revision: int,
    ) -> DefinitionVersion:
        return await _publish_definition(
            self._session,
            kind=kind,
            definition_id=definition_id,
            owner_org_id=owner_org_id,
            expected_revision=expected_revision,
        )

    async def deprecate(
        self,
        *,
        kind: DefinitionKind,
        definition_id: uuid.UUID,
        owner_org_id: uuid.UUID | None,
    ) -> DefinitionVersion:
        return await _deprecate_definition(
            self._session,
            kind=kind,
            definition_id=definition_id,
            owner_org_id=owner_org_id,
        )

    async def compile_definition_bundle(
        self,
        *,
        org_id: uuid.UUID,
        request: CompileBundleRequest,
    ) -> DefinitionBundle:
        version_ids = self._compiler.collect_version_ids(request)
        locked = await _lock_visible_definition_versions(
            self._session,
            org_id=org_id,
            version_ids_by_kind=version_ids,
        )
        catalog = DefinitionCatalog(
            domain_packages={
                row.id: self._snapshot("domain_package", row) for row in locked["domain_package"]
            },
            works={row.id: self._snapshot("work", row) for row in locked["work"]},
            roles={row.id: self._snapshot("role", row) for row in locked["role"]},
        )
        plan = self._compiler.plan(org_id=org_id, request=request, catalog=catalog)

        references_by_path: dict[tuple[str, ...], CompiledBundleReference] = {}
        bundles_by_path: dict[tuple[str, ...], DefinitionBundle] = {}
        for node in plan.postorder:
            child_references = {
                dependency_key: references_by_path[child.path]
                for dependency_key, child in node.children
            }
            draft = self._compiler.compile_node(
                node,
                child_bundles_by_key=child_references,
            )
            bundle = await self._find_or_stage_bundle(org_id=org_id, draft=draft)
            references_by_path[node.path] = CompiledBundleReference(
                bundle_id=bundle.id,
                checksum=bundle.checksum,
            )
            bundles_by_path[node.path] = bundle
        return bundles_by_path[()]

    @staticmethod
    def _snapshot(
        kind: DefinitionKind,
        row: DefinitionVersion,
    ) -> DefinitionVersionSnapshot:
        return DefinitionVersionSnapshot(
            id=row.id,
            kind=kind,
            owner_org_id=row.owner_org_id,
            key=row.key,
            version=row.version,
            visibility=cast(Literal["public", "private"], row.visibility),
            status=cast(Literal["draft", "published", "deprecated"], row.status),
            checksum=row.checksum,
            definition=dict(row.definition),
        )

    async def _find_or_stage_bundle(
        self,
        *,
        org_id: uuid.UUID,
        draft: CompiledBundleDraft,
    ) -> DefinitionBundle:
        existing = await find_bundle_by_checksum(
            self._session,
            org_id=org_id,
            checksum=draft.checksum,
        )
        if existing is not None:
            self._assert_existing_matches(existing, draft)
            return existing

        bundle = DefinitionBundle(
            org_id=org_id,
            domain_package_version_id=draft.domain_package_version_id,
            work_definition_version_id=draft.work_definition_version_id,
            compiled_definition=draft.compiled_definition,
            checksum=draft.checksum,
            compiler_version=draft.compiler_version,
            kernel_contract_version=draft.kernel_contract_version,
            min_kernel_version=draft.min_kernel_version,
            child_work_bundle_dependencies=draft.child_work_bundle_dependencies,
        )
        role_rows = [
            DefinitionBundleRole(
                org_id=org_id,
                role_slot_key=role.role_slot_key,
                role_definition_version_id=role.role_definition_version_id,
            )
            for role in draft.roles
        ]
        dependency_rows = [
            DefinitionBundleDependency(
                org_id=org_id,
                dependency_key=dependency.dependency_key,
                trigger_key=dependency.trigger_key,
                child_bundle_id=dependency.child_bundle_id,
                child_bundle_checksum=dependency.child_bundle_checksum,
            )
            for dependency in draft.dependencies
        ]
        try:
            async with self._session.begin_nested():
                await _add_bundle_snapshot(
                    self._session,
                    bundle=bundle,
                    roles=role_rows,
                    dependencies=dependency_rows,
                )
        except IntegrityError:
            existing = await find_bundle_by_checksum(
                self._session,
                org_id=org_id,
                checksum=draft.checksum,
            )
            if existing is None:
                raise
            self._assert_existing_matches(existing, draft)
            return existing
        return bundle

    @staticmethod
    def _assert_existing_matches(
        existing: DefinitionBundle,
        draft: CompiledBundleDraft,
    ) -> None:
        actual = (
            existing.domain_package_version_id,
            existing.work_definition_version_id,
            existing.compiled_definition,
            existing.compiler_version,
            existing.kernel_contract_version,
            existing.min_kernel_version,
            existing.child_work_bundle_dependencies,
        )
        expected = (
            draft.domain_package_version_id,
            draft.work_definition_version_id,
            draft.compiled_definition,
            draft.compiler_version,
            draft.kernel_contract_version,
            draft.min_kernel_version,
            draft.child_work_bundle_dependencies,
        )
        if actual != expected:
            raise KernelProtocolError(
                "BUNDLE_INCOMPATIBLE",
                "/checksum",
                "existing bundle checksum resolves to different compiled content",
            )


__all__ = ["DefinitionCommandService"]
