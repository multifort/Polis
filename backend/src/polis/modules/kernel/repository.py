"""Persistence boundary for V3 Definition versions and compiled bundles.

Repositories never commit.  Definition mutation is limited to draft replacement,
publish and deprecate; compiled bundles expose insert/read operations only.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Literal, cast

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from polis.modules.kernel.errors import KernelProtocolError
from polis.modules.kernel.models import (
    DefinitionBundle,
    DefinitionBundleDependency,
    DefinitionBundleRole,
    DefinitionVersionMixin,
    DomainPackageVersion,
    RoleDefinitionVersion,
    WorkDefinitionVersion,
)
from polis.modules.kernel.schemas import (
    DEFINITION_V1_ADAPTER,
    DefinitionV1,
    definition_checksum,
    validate_semver,
)

type DefinitionKind = Literal["domain_package", "role", "work"]
type DefinitionVersion = DomainPackageVersion | RoleDefinitionVersion | WorkDefinitionVersion

DEFINITION_MODEL_BY_KIND: dict[DefinitionKind, type[DefinitionVersionMixin]] = {
    "domain_package": DomainPackageVersion,
    "role": RoleDefinitionVersion,
    "work": WorkDefinitionVersion,
}


def _visibility_owner_clause[DefinitionRowT: DefinitionVersionMixin](
    model: type[DefinitionRowT], owner_org_id: uuid.UUID | None
) -> Any:
    if owner_org_id is None:
        return model.owner_org_id.is_(None)
    return model.owner_org_id == owner_org_id


def _validate_definition(
    *, kind: DefinitionKind, key: str, definition: dict[str, Any]
) -> DefinitionV1:
    parsed = DEFINITION_V1_ADAPTER.validate_python(definition)
    if parsed.definition_kind != kind:
        raise KernelProtocolError(
            "DEFINITION_KIND_MISMATCH",
            "/definition_kind",
            f"expected '{kind}', got '{parsed.definition_kind}'",
        )
    if parsed.key != key:
        raise KernelProtocolError(
            "DEFINITION_KEY_INVALID",
            "/key",
            f"definition key '{parsed.key}' does not match row key '{key}'",
        )
    return parsed


async def _find_owned[DefinitionRowT: DefinitionVersionMixin](
    session: AsyncSession,
    model: type[DefinitionRowT],
    definition_id: uuid.UUID,
    owner_org_id: uuid.UUID | None,
    *,
    for_update: bool = False,
) -> DefinitionRowT | None:
    statement = select(model).where(
        model.id == definition_id,
        _visibility_owner_clause(model, owner_org_id),
    )
    if for_update:
        statement = statement.with_for_update()
    return cast(DefinitionRowT | None, await session.scalar(statement))


async def create_definition_draft(
    session: AsyncSession,
    *,
    kind: DefinitionKind,
    owner_org_id: uuid.UUID | None,
    key: str,
    version: str,
    visibility: Literal["public", "private"],
    definition: dict[str, Any],
    created_by: uuid.UUID | None,
) -> DefinitionVersion:
    """Validate and stage a new draft without committing the caller transaction."""

    validate_semver(version)
    if (visibility == "public") != (owner_org_id is None):
        raise KernelProtocolError(
            "DEFINITION_VISIBILITY_INVALID",
            "/visibility",
            "public definitions require no owner; private definitions require an owner",
        )
    parsed = _validate_definition(kind=kind, key=key, definition=definition)
    model = DEFINITION_MODEL_BY_KIND[kind]
    duplicate = await session.scalar(
        select(model.id).where(
            _visibility_owner_clause(model, owner_org_id),
            model.key == key,
            model.version == version,
        )
    )
    if duplicate is not None:
        raise KernelProtocolError(
            "DEFINITION_ALREADY_EXISTS",
            "",
            f"definition '{key}@{version}' already exists in this owner scope",
        )
    row = model()
    row.owner_org_id = owner_org_id
    row.key = key
    row.version = version
    row.visibility = visibility
    row.status = "draft"
    row.schema_version = 1
    row.revision = 1
    row.definition = parsed.model_dump(mode="json", by_alias=True)
    row.checksum = definition_checksum(parsed)
    row.created_by = created_by
    row.published_at = None
    session.add(row)
    await session.flush()
    return cast(DefinitionVersion, row)


async def get_visible_definition(
    session: AsyncSession,
    *,
    kind: DefinitionKind,
    definition_id: uuid.UUID,
    org_id: uuid.UUID,
) -> DefinitionVersion | None:
    """Return own private or platform public definition; hide other private rows."""

    model = DEFINITION_MODEL_BY_KIND[kind]
    return cast(
        DefinitionVersion | None,
        await session.scalar(
            select(model).where(
                model.id == definition_id,
                or_(
                    model.owner_org_id == org_id,
                    and_(model.owner_org_id.is_(None), model.visibility == "public"),
                ),
            )
        ),
    )


async def update_definition_draft(
    session: AsyncSession,
    *,
    kind: DefinitionKind,
    definition_id: uuid.UUID,
    owner_org_id: uuid.UUID | None,
    expected_revision: int,
    definition: dict[str, Any],
) -> DefinitionVersion:
    model = DEFINITION_MODEL_BY_KIND[kind]
    row = await _find_owned(session, model, definition_id, owner_org_id, for_update=True)
    if row is None:
        raise KernelProtocolError("DEFINITION_NOT_FOUND", "", "definition not found")
    if row.status != "draft":
        raise KernelProtocolError(
            "DEFINITION_IMMUTABLE", "/status", "only draft definitions can be updated"
        )
    if row.revision != expected_revision:
        raise KernelProtocolError(
            "DEFINITION_REVISION_CONFLICT",
            "/revision",
            f"expected revision {expected_revision}, found {row.revision}",
        )
    parsed = _validate_definition(kind=kind, key=row.key, definition=definition)
    row.definition = parsed.model_dump(mode="json", by_alias=True)
    row.checksum = definition_checksum(parsed)
    row.revision += 1
    await session.flush()
    return cast(DefinitionVersion, row)


async def publish_definition(
    session: AsyncSession,
    *,
    kind: DefinitionKind,
    definition_id: uuid.UUID,
    owner_org_id: uuid.UUID | None,
    expected_revision: int,
) -> DefinitionVersion:
    model = DEFINITION_MODEL_BY_KIND[kind]
    row = await _find_owned(session, model, definition_id, owner_org_id, for_update=True)
    if row is None:
        raise KernelProtocolError("DEFINITION_NOT_FOUND", "", "definition not found")
    if row.status != "draft":
        raise KernelProtocolError(
            "DEFINITION_IMMUTABLE", "/status", "only draft definitions can be published"
        )
    if row.revision != expected_revision:
        raise KernelProtocolError(
            "DEFINITION_REVISION_CONFLICT",
            "/revision",
            f"expected revision {expected_revision}, found {row.revision}",
        )
    row.status = "published"
    row.published_at = datetime.now(UTC)
    await session.flush()
    return cast(DefinitionVersion, row)


async def deprecate_definition(
    session: AsyncSession,
    *,
    kind: DefinitionKind,
    definition_id: uuid.UUID,
    owner_org_id: uuid.UUID | None,
) -> DefinitionVersion:
    model = DEFINITION_MODEL_BY_KIND[kind]
    row = await _find_owned(session, model, definition_id, owner_org_id, for_update=True)
    if row is None:
        raise KernelProtocolError("DEFINITION_NOT_FOUND", "", "definition not found")
    if row.status != "published":
        raise KernelProtocolError(
            "DEFINITION_STATUS_INVALID",
            "/status",
            "only published definitions can be deprecated",
        )
    row.status = "deprecated"
    await session.flush()
    return cast(DefinitionVersion, row)


async def find_bundle_by_checksum(
    session: AsyncSession, *, org_id: uuid.UUID, checksum: str
) -> DefinitionBundle | None:
    return cast(
        DefinitionBundle | None,
        await session.scalar(
            select(DefinitionBundle).where(
                DefinitionBundle.org_id == org_id,
                DefinitionBundle.checksum == checksum,
            )
        ),
    )


async def get_bundle(
    session: AsyncSession, *, org_id: uuid.UUID, bundle_id: uuid.UUID
) -> DefinitionBundle | None:
    return cast(
        DefinitionBundle | None,
        await session.scalar(
            select(DefinitionBundle).where(
                DefinitionBundle.org_id == org_id,
                DefinitionBundle.id == bundle_id,
            )
        ),
    )


async def add_bundle_snapshot(
    session: AsyncSession,
    *,
    bundle: DefinitionBundle,
    roles: list[DefinitionBundleRole],
    dependencies: list[DefinitionBundleDependency],
) -> DefinitionBundle:
    """Stage a compiler-produced immutable bundle graph in one transaction."""

    if any(role.org_id != bundle.org_id for role in roles) or any(
        dependency.org_id != bundle.org_id for dependency in dependencies
    ):
        raise KernelProtocolError(
            "BUNDLE_ORG_MISMATCH", "/org_id", "all bundle rows must belong to one org"
        )
    session.add(bundle)
    await session.flush()
    for role in roles:
        role.bundle_id = bundle.id
    for dependency in dependencies:
        dependency.parent_bundle_id = bundle.id
    session.add_all([*roles, *dependencies])
    await session.flush()
    return bundle


__all__ = [
    "DEFINITION_MODEL_BY_KIND",
    "DefinitionKind",
    "DefinitionVersion",
    "add_bundle_snapshot",
    "create_definition_draft",
    "deprecate_definition",
    "find_bundle_by_checksum",
    "get_bundle",
    "get_visible_definition",
    "publish_definition",
    "update_definition_draft",
]
