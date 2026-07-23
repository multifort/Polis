"""K1 Scope-family application service and governance bootstrap."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import ValidationError
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from polis.modules.kernel.domain.governance import (
    GOVERNANCE_DOMAIN_KEY,
    GOVERNANCE_OWNER_ROLE_KEY,
    GOVERNANCE_SCOPE_TYPE,
)
from polis.modules.kernel.errors import KernelProtocolError
from polis.modules.kernel.models import (
    DomainPackageVersion,
    OrgKernelSetting,
    RoleDefinitionVersion,
    Scope,
    ScopeRelation,
    ScopeRoleAssignment,
    ServiceIdentity,
)
from polis.modules.kernel.schemas import (
    AuthorityConstraintsV1,
    DomainPackageDefinitionV1,
    OrgPolicyV1,
    RoleDefinitionV1,
)
from polis.modules.org.models import Agent, AppUser, Org, OrgMember

type ActorKind = Literal["human", "agent", "service"]


def _fail(code: str, path: str, message: str) -> KernelProtocolError:
    return KernelProtocolError(code, path, message)


class ScopeCommandService:
    """Only K1 write surface for Scope and ScopeRoleAssignment state."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_scope(
        self,
        *,
        org_id: uuid.UUID,
        actor_kind: ActorKind,
        actor_ref: uuid.UUID,
        domain_package_version_id: uuid.UUID,
        scope_type: str,
        display_name: str,
        attributes: dict[str, Any],
        parent_scope_id: uuid.UUID | None = None,
        external_ref: str | None = None,
    ) -> Scope:
        setting = await self._setting(org_id, for_update=True)
        await self._validate_actor(org_id, actor_kind, actor_ref)
        domain, declaration = await self._domain(org_id, domain_package_version_id)

        if scope_type == GOVERNANCE_SCOPE_TYPE:
            if setting.governance_state != "uninitialized":
                raise _fail(
                    "GOVERNANCE_SCOPE_ALREADY_EXISTS",
                    "/scope_type",
                    "organization governance is already active",
                )
            await self._require_bootstrap_owner(org_id, actor_kind, actor_ref)
            existing_governance = await self._session.scalar(
                select(Scope.id).where(
                    Scope.org_id == org_id,
                    Scope.scope_type == GOVERNANCE_SCOPE_TYPE,
                )
            )
            if existing_governance is not None:
                raise _fail(
                    "GOVERNANCE_SCOPE_ALREADY_EXISTS",
                    "/scope_type",
                    "organization governance scope already exists",
                )
            if domain.key != GOVERNANCE_DOMAIN_KEY:
                raise _fail(
                    "GOVERNANCE_DOMAIN_REQUIRED",
                    "/domain_package_version_id",
                    "governance scope requires the platform governance domain",
                )
            if parent_scope_id is not None or external_ref is not None:
                raise _fail(
                    "GOVERNANCE_SCOPE_INVALID",
                    "",
                    "governance scope cannot have a parent or external reference",
                )
            if display_name != "Organization Governance":
                raise _fail(
                    "GOVERNANCE_SCOPE_INVALID",
                    "/display_name",
                    "governance display name is fixed",
                )
            self._policy(attributes)
        else:
            if domain.key == GOVERNANCE_DOMAIN_KEY:
                raise _fail(
                    "SCOPE_TYPE_INVALID",
                    "/scope_type",
                    "the governance domain only declares org_governance",
                )
            await self._authorize(
                org_id=org_id,
                actor_kind=actor_kind,
                actor_ref=actor_ref,
                command="create_scope",
                target_scope_id=None,
            )

        scope_declaration = next(
            (item for item in declaration.scope_types if item.key == scope_type),
            None,
        )
        if scope_declaration is None:
            raise _fail(
                "SCOPE_TYPE_INVALID",
                "/scope_type",
                f"scope type '{scope_type}' is not declared by the domain",
            )
        scope_declaration.attributes_schema.validate_instance(attributes)

        if parent_scope_id is not None:
            parent = await self._scope(org_id, parent_scope_id)
            if parent.status != "active":
                raise _fail("SCOPE_PARENT_INVALID", "/parent_scope_id", "parent is archived")
            if parent.scope_type not in scope_declaration.parent_types:
                raise _fail(
                    "SCOPE_PARENT_TYPE_INVALID",
                    "/parent_scope_id",
                    f"parent type '{parent.scope_type}' is not allowed",
                )

        row = Scope(
            org_id=org_id,
            domain_package_version_id=domain.id,
            scope_type=scope_type,
            parent_scope_id=parent_scope_id,
            external_ref=external_ref,
            display_name=display_name,
            attributes=attributes,
            status="active",
            version=1,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def update_scope(
        self,
        *,
        org_id: uuid.UUID,
        scope_id: uuid.UUID,
        actor_kind: ActorKind,
        actor_ref: uuid.UUID,
        expected_version: int,
        display_name: str,
        attributes: dict[str, Any],
    ) -> tuple[Scope, bool]:
        row = await self._scope(org_id, scope_id, for_update=True)
        if row.version != expected_version:
            raise _fail(
                "SCOPE_VERSION_CONFLICT",
                "/version",
                f"expected version {expected_version}, found {row.version}",
            )
        await self._authorize(
            org_id=org_id,
            actor_kind=actor_kind,
            actor_ref=actor_ref,
            command="update_scope",
            target_scope_id=row.id,
        )
        _, declaration = await self._domain(org_id, row.domain_package_version_id)
        scope_declaration = next(
            item for item in declaration.scope_types if item.key == row.scope_type
        )
        scope_declaration.attributes_schema.validate_instance(attributes)

        if row.scope_type == GOVERNANCE_SCOPE_TYPE:
            if display_name != "Organization Governance":
                raise _fail(
                    "GOVERNANCE_SCOPE_INVALID",
                    "/display_name",
                    "governance display name is fixed",
                )
            current = self._policy(row.attributes)
            proposed = self._policy(attributes)
            if current.checksum == proposed.checksum:
                return row, False

        if row.display_name == display_name and row.attributes == attributes:
            return row, False
        row.display_name = display_name
        row.attributes = attributes
        row.version += 1
        await self._session.flush()
        return row, True

    async def assign_scope_role(
        self,
        *,
        org_id: uuid.UUID,
        scope_id: uuid.UUID,
        actor_kind: ActorKind,
        actor_ref: uuid.UUID,
        role_definition_version_id: uuid.UUID,
        assignee_kind: ActorKind,
        assignee_ref: uuid.UUID,
        inheritance_mode: Literal["none", "descendants"],
        authority_constraints: dict[str, Any],
    ) -> ScopeRoleAssignment:
        scope = await self._scope(org_id, scope_id, for_update=True)
        setting = await self._setting(org_id, for_update=True)
        await self._validate_actor(org_id, actor_kind, actor_ref)
        if setting.governance_state == "uninitialized":
            if scope.scope_type != GOVERNANCE_SCOPE_TYPE:
                raise _fail(
                    "GOVERNANCE_BOOTSTRAP_ONLY",
                    "/scope_id",
                    "only the governance scope can be assigned during bootstrap",
                )
            await self._require_bootstrap_owner(org_id, actor_kind, actor_ref)
        else:
            await self._authorize(
                org_id=org_id,
                actor_kind=actor_kind,
                actor_ref=actor_ref,
                command="assign_scope_role",
                target_scope_id=scope.id,
            )

        role, role_definition = await self._role(org_id, role_definition_version_id)
        if setting.governance_state == "uninitialized" and role.key != GOVERNANCE_OWNER_ROLE_KEY:
            raise _fail(
                "GOVERNANCE_OWNER_ROLE_REQUIRED",
                "/role_definition_version_id",
                "bootstrap requires the platform governance owner role",
            )
        await self._validate_actor(org_id, assignee_kind, assignee_ref)
        try:
            constraints = AuthorityConstraintsV1.model_validate(authority_constraints)
        except ValidationError as exc:
            raise _fail(
                "ASSIGNMENT_AUTHORITY_INVALID",
                "/authority_constraints",
                "authority constraints do not match AuthorityConstraintsV1",
            ) from exc
        constraints.validate_subset_of(role_definition.authority)

        row = ScopeRoleAssignment(
            org_id=org_id,
            scope_id=scope.id,
            role_definition_version_id=role.id,
            actor_kind=assignee_kind,
            actor_ref=assignee_ref,
            inheritance_mode=inheritance_mode,
            authority_constraints=constraints.canonical_value(),
            status="pending",
            valid_from=None,
            valid_until=None,
            assigned_by_kind=actor_kind,
            assigned_by_ref=actor_ref,
            version=1,
        )
        self._session.add(row)
        scope.version += 1
        await self._session.flush()
        return row

    async def relate_scopes(
        self,
        *,
        org_id: uuid.UUID,
        from_scope_id: uuid.UUID,
        to_scope_id: uuid.UUID,
        actor_kind: ActorKind,
        actor_ref: uuid.UUID,
        relationship_type: str,
        attributes: dict[str, Any],
    ) -> ScopeRelation:
        if from_scope_id == to_scope_id:
            raise _fail(
                "SCOPE_RELATION_SELF_INVALID",
                "/to_scope_id",
                "a scope cannot be related to itself",
            )
        await self._authorize(
            org_id=org_id,
            actor_kind=actor_kind,
            actor_ref=actor_ref,
            command="relate_scopes",
            target_scope_id=from_scope_id,
        )
        scope_ids = sorted((from_scope_id, to_scope_id), key=str)
        rows = list(
            (
                await self._session.scalars(
                    select(Scope)
                    .where(Scope.org_id == org_id, Scope.id.in_(scope_ids))
                    .order_by(Scope.id)
                    .with_for_update()
                )
            ).all()
        )
        scopes = {row.id: row for row in rows}
        if set(scopes) != set(scope_ids):
            raise _fail(
                "SCOPE_NOT_FOUND",
                "",
                "both relation endpoints must exist in the organization",
            )
        from_scope = scopes[from_scope_id]
        to_scope = scopes[to_scope_id]
        if from_scope.status != "active" or to_scope.status != "active":
            raise _fail(
                "SCOPE_RELATION_ENDPOINT_INVALID",
                "",
                "both relation endpoints must be active",
            )
        if from_scope.domain_package_version_id != to_scope.domain_package_version_id:
            raise _fail(
                "SCOPE_RELATION_DOMAIN_MISMATCH",
                "",
                "relation endpoints must use the same domain package version",
            )
        domain, declaration = await self._domain(org_id, from_scope.domain_package_version_id)
        relation = next(
            (item for item in declaration.relationship_types if item.key == relationship_type),
            None,
        )
        if relation is None:
            raise _fail(
                "RELATIONSHIP_TYPE_INVALID",
                "/relationship_type",
                "relationship type is not declared by the domain",
            )
        if relation.directed:
            valid_types = (
                from_scope.scope_type in relation.from_scope_types
                and to_scope.scope_type in relation.to_scope_types
            )
        else:
            valid_types = (
                from_scope.scope_type in relation.from_scope_types
                and to_scope.scope_type in relation.to_scope_types
            ) or (
                to_scope.scope_type in relation.from_scope_types
                and from_scope.scope_type in relation.to_scope_types
            )
            if str(from_scope.id) > str(to_scope.id):
                from_scope, to_scope = to_scope, from_scope
        if not valid_types:
            raise _fail(
                "SCOPE_RELATION_TYPE_INVALID",
                "",
                "endpoint scope types are not allowed by the relationship",
            )
        relation.attributes_schema.validate_instance(attributes)
        duplicate = await self._session.scalar(
            select(ScopeRelation.id).where(
                ScopeRelation.org_id == org_id,
                ScopeRelation.relationship_type == relationship_type,
                ScopeRelation.from_scope_id == from_scope.id,
                ScopeRelation.to_scope_id == to_scope.id,
                ScopeRelation.status == "active",
            )
        )
        if duplicate is not None:
            raise _fail(
                "SCOPE_RELATION_ALREADY_EXISTS",
                "",
                "the active scope relation already exists",
            )
        cardinality_filters = []
        if relation.cardinality in ("one_to_one", "many_to_one"):
            cardinality_filters.append(ScopeRelation.from_scope_id == from_scope.id)
        if relation.cardinality in ("one_to_one", "one_to_many"):
            cardinality_filters.append(ScopeRelation.to_scope_id == to_scope.id)
        if not relation.directed and relation.cardinality == "one_to_one":
            cardinality_filters.extend(
                (
                    ScopeRelation.from_scope_id.in_((from_scope.id, to_scope.id)),
                    ScopeRelation.to_scope_id.in_((from_scope.id, to_scope.id)),
                )
            )
        if cardinality_filters:
            occupied = await self._session.scalar(
                select(ScopeRelation.id).where(
                    ScopeRelation.org_id == org_id,
                    ScopeRelation.relationship_type == relationship_type,
                    ScopeRelation.status == "active",
                    or_(*cardinality_filters),
                )
            )
            if occupied is not None:
                raise _fail(
                    "SCOPE_RELATION_CARDINALITY_EXCEEDED",
                    "",
                    "the relationship cardinality would be exceeded",
                )
        row = ScopeRelation(
            org_id=org_id,
            domain_package_version_id=domain.id,
            relationship_type=relationship_type,
            from_scope_id=from_scope.id,
            to_scope_id=to_scope.id,
            attributes=attributes,
            status="active",
            version=1,
            created_by_kind=actor_kind,
            created_by_ref=actor_ref,
            ended_at=None,
        )
        self._session.add(row)
        from_scope.version += 1
        to_scope.version += 1
        await self._session.flush()
        return row

    async def activate_scope_role(
        self,
        *,
        org_id: uuid.UUID,
        assignment_id: uuid.UUID,
        actor_kind: ActorKind,
        actor_ref: uuid.UUID,
        expected_version: int,
    ) -> ScopeRoleAssignment:
        assignment = await self._assignment(org_id, assignment_id, for_update=True)
        scope = await self._scope(org_id, assignment.scope_id, for_update=True)
        setting = await self._setting(org_id, for_update=True)
        if assignment.version != expected_version:
            raise _fail(
                "ASSIGNMENT_VERSION_CONFLICT",
                "/version",
                f"expected version {expected_version}, found {assignment.version}",
            )
        if assignment.status != "pending":
            raise _fail(
                "ASSIGNMENT_STATE_INVALID",
                "/status",
                "only pending assignments can be activated",
            )

        if setting.governance_state == "uninitialized":
            await self._require_bootstrap_owner(org_id, actor_kind, actor_ref)
            role, _ = await self._role(org_id, assignment.role_definition_version_id)
            if scope.scope_type != GOVERNANCE_SCOPE_TYPE or role.key != GOVERNANCE_OWNER_ROLE_KEY:
                raise _fail(
                    "GOVERNANCE_BOOTSTRAP_INVALID",
                    "",
                    "the initial active assignment must own the governance scope",
                )
            self._policy(scope.attributes)
            assignment.status = "active"
            assignment.valid_from = datetime.now(UTC)
            assignment.version += 1
            scope.version += 1
            setting.governance_scope_id = scope.id
            setting.governance_state = "active"
            setting.config_version += 1
            setting.changed_by = actor_ref if actor_kind == "human" else None
            setting.changed_at = datetime.now(UTC)
        else:
            await self._authorize(
                org_id=org_id,
                actor_kind=actor_kind,
                actor_ref=actor_ref,
                command="activate_scope_role",
                target_scope_id=scope.id,
            )
            assignment.status = "active"
            assignment.valid_from = datetime.now(UTC)
            assignment.version += 1
            scope.version += 1
        await self._session.flush()
        return assignment

    async def get_scope(self, *, org_id: uuid.UUID, scope_id: uuid.UUID) -> Scope:
        return await self._scope(org_id, scope_id)

    async def list_scopes(
        self,
        *,
        org_id: uuid.UUID,
        scope_type: str | None = None,
        parent_scope_id: uuid.UUID | None = None,
    ) -> list[Scope]:
        statement = select(Scope).where(Scope.org_id == org_id)
        if scope_type is not None:
            statement = statement.where(Scope.scope_type == scope_type)
        if parent_scope_id is not None:
            statement = statement.where(Scope.parent_scope_id == parent_scope_id)
        return list(
            (await self._session.scalars(statement.order_by(Scope.created_at, Scope.id))).all()
        )

    async def list_scope_relations(
        self, *, org_id: uuid.UUID, scope_id: uuid.UUID
    ) -> list[ScopeRelation]:
        return list(
            (
                await self._session.scalars(
                    select(ScopeRelation)
                    .where(
                        ScopeRelation.org_id == org_id,
                        or_(
                            ScopeRelation.from_scope_id == scope_id,
                            ScopeRelation.to_scope_id == scope_id,
                        ),
                    )
                    .order_by(ScopeRelation.created_at, ScopeRelation.id)
                )
            ).all()
        )

    async def _authorize(
        self,
        *,
        org_id: uuid.UUID,
        actor_kind: ActorKind,
        actor_ref: uuid.UUID,
        command: str,
        target_scope_id: uuid.UUID | None,
    ) -> None:
        await self._validate_actor(org_id, actor_kind, actor_ref)
        setting = await self._setting(org_id)
        if setting.governance_state != "active" or setting.governance_scope_id is None:
            raise _fail(
                "GOVERNANCE_NOT_INITIALIZED",
                "",
                "organization governance is not active",
            )
        now = datetime.now(UTC)
        allowed_scope_ids = [setting.governance_scope_id]
        if target_scope_id is not None:
            allowed_scope_ids.append(target_scope_id)
        rows = (
            await self._session.execute(
                select(ScopeRoleAssignment, RoleDefinitionVersion)
                .join(
                    RoleDefinitionVersion,
                    RoleDefinitionVersion.id == ScopeRoleAssignment.role_definition_version_id,
                )
                .where(
                    ScopeRoleAssignment.org_id == org_id,
                    ScopeRoleAssignment.scope_id.in_(allowed_scope_ids),
                    ScopeRoleAssignment.actor_kind == actor_kind,
                    ScopeRoleAssignment.actor_ref == actor_ref,
                    ScopeRoleAssignment.status == "active",
                    or_(
                        ScopeRoleAssignment.valid_from.is_(None),
                        ScopeRoleAssignment.valid_from <= now,
                    ),
                    or_(
                        ScopeRoleAssignment.valid_until.is_(None),
                        ScopeRoleAssignment.valid_until > now,
                    ),
                )
            )
        ).all()
        for assignment, role in rows:
            parsed = RoleDefinitionV1.model_validate(role.definition)
            constraints = AuthorityConstraintsV1.model_validate(assignment.authority_constraints)
            constraints.validate_subset_of(parsed.authority)
            command_constraints = constraints.commands
            if command in parsed.authority.commands and (
                command_constraints is None or command in command_constraints
            ):
                return
        raise _fail(
            "SCOPE_COMMAND_FORBIDDEN",
            "/command_type",
            f"actor has no active assignment permitting '{command}'",
        )

    async def _setting(self, org_id: uuid.UUID, *, for_update: bool = False) -> OrgKernelSetting:
        statement = select(OrgKernelSetting).where(OrgKernelSetting.org_id == org_id)
        if for_update:
            statement = statement.with_for_update()
        row = await self._session.scalar(statement)
        if row is None:
            raise _fail("ORG_NOT_FOUND", "/org_id", "organization setting not found")
        return row

    async def _scope(
        self, org_id: uuid.UUID, scope_id: uuid.UUID, *, for_update: bool = False
    ) -> Scope:
        statement = select(Scope).where(Scope.org_id == org_id, Scope.id == scope_id)
        if for_update:
            statement = statement.with_for_update()
        row = await self._session.scalar(statement)
        if row is None:
            raise _fail("SCOPE_NOT_FOUND", "/scope_id", "scope not found")
        return row

    async def _assignment(
        self,
        org_id: uuid.UUID,
        assignment_id: uuid.UUID,
        *,
        for_update: bool = False,
    ) -> ScopeRoleAssignment:
        statement = select(ScopeRoleAssignment).where(
            ScopeRoleAssignment.org_id == org_id,
            ScopeRoleAssignment.id == assignment_id,
        )
        if for_update:
            statement = statement.with_for_update()
        row = await self._session.scalar(statement)
        if row is None:
            raise _fail("ASSIGNMENT_NOT_FOUND", "/assignment_id", "assignment not found")
        return row

    async def _domain(
        self, org_id: uuid.UUID, definition_id: uuid.UUID
    ) -> tuple[DomainPackageVersion, DomainPackageDefinitionV1]:
        row = await self._session.scalar(
            select(DomainPackageVersion).where(
                DomainPackageVersion.id == definition_id,
                DomainPackageVersion.status == "published",
                or_(
                    and_(
                        DomainPackageVersion.owner_org_id.is_(None),
                        DomainPackageVersion.visibility == "public",
                    ),
                    and_(
                        DomainPackageVersion.owner_org_id == org_id,
                        DomainPackageVersion.visibility == "private",
                    ),
                ),
            )
        )
        if row is None:
            raise _fail(
                "DOMAIN_PACKAGE_NOT_FOUND",
                "/domain_package_version_id",
                "published domain package is not visible",
            )
        return row, DomainPackageDefinitionV1.model_validate(row.definition)

    async def _role(
        self, org_id: uuid.UUID, definition_id: uuid.UUID
    ) -> tuple[RoleDefinitionVersion, RoleDefinitionV1]:
        row = await self._session.scalar(
            select(RoleDefinitionVersion).where(
                RoleDefinitionVersion.id == definition_id,
                RoleDefinitionVersion.status == "published",
                or_(
                    and_(
                        RoleDefinitionVersion.owner_org_id.is_(None),
                        RoleDefinitionVersion.visibility == "public",
                    ),
                    and_(
                        RoleDefinitionVersion.owner_org_id == org_id,
                        RoleDefinitionVersion.visibility == "private",
                    ),
                ),
            )
        )
        if row is None:
            raise _fail(
                "ROLE_DEFINITION_NOT_FOUND",
                "/role_definition_version_id",
                "published role definition is not visible",
            )
        return row, RoleDefinitionV1.model_validate(row.definition)

    async def _require_bootstrap_owner(
        self, org_id: uuid.UUID, actor_kind: ActorKind, actor_ref: uuid.UUID
    ) -> None:
        if actor_kind != "human":
            raise _fail(
                "GOVERNANCE_BOOTSTRAP_FORBIDDEN",
                "/actor_kind",
                "bootstrap requires the organization owner",
            )
        owner = await self._session.scalar(
            select(Org.id)
            .join(
                OrgMember,
                and_(
                    OrgMember.org_id == Org.id,
                    OrgMember.user_id == actor_ref,
                    OrgMember.role == "owner",
                ),
            )
            .where(Org.id == org_id, Org.owner_user_id == actor_ref)
        )
        if owner is None:
            raise _fail(
                "GOVERNANCE_BOOTSTRAP_FORBIDDEN",
                "/actor_ref",
                "bootstrap requires the organization owner",
            )

    async def _validate_actor(
        self, org_id: uuid.UUID, actor_kind: ActorKind, actor_ref: uuid.UUID
    ) -> None:
        if actor_kind == "human":
            found = await self._session.scalar(
                select(AppUser.id)
                .join(OrgMember, OrgMember.user_id == AppUser.id)
                .where(
                    AppUser.id == actor_ref,
                    AppUser.status == "active",
                    OrgMember.org_id == org_id,
                )
            )
        elif actor_kind == "agent":
            found = await self._session.scalar(
                select(Agent.id).where(
                    Agent.id == actor_ref,
                    Agent.org_id == org_id,
                    Agent.status == "active",
                )
            )
        else:
            found = await self._session.scalar(
                select(ServiceIdentity.id).where(
                    ServiceIdentity.id == actor_ref,
                    ServiceIdentity.org_id == org_id,
                    ServiceIdentity.status == "active",
                )
            )
        if found is None:
            raise _fail(
                "ACTOR_INVALID",
                "/actor_ref",
                "actor does not exist as an active identity in this organization",
            )

    @staticmethod
    def _policy(value: dict[str, Any]) -> OrgPolicyV1:
        try:
            return OrgPolicyV1.model_validate(value)
        except ValidationError as exc:
            raise _fail(
                "ORG_POLICY_INVALID",
                "/attributes",
                "attributes do not match OrgPolicyV1",
            ) from exc


__all__ = ["ActorKind", "ScopeCommandService"]
