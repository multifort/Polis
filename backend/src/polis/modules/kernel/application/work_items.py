"""K1 WorkItem creation, query and responsibility binding services."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from polis.modules.kernel.application.scope_commands import ActorKind, ScopeCommandService
from polis.modules.kernel.errors import KernelProtocolError
from polis.modules.kernel.models import (
    DefinitionBundle,
    Scope,
    ScopeRoleAssignment,
    WorkItem,
    WorkRoleBinding,
)
from polis.modules.kernel.schemas import WorkDefinitionV1


def _fail(code: str, path: str, message: str) -> KernelProtocolError:
    return KernelProtocolError(code, path, message)


class WorkItemService:
    """K1 persistence boundary; K2 adds Command receipts and transitions around it."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._scope_service = ScopeCommandService(session)

    async def create_work_item(
        self,
        *,
        org_id: uuid.UUID,
        scope_id: uuid.UUID,
        definition_bundle_id: uuid.UUID,
        title: str,
        inputs: dict[str, Any],
        created_by_kind: ActorKind,
        created_by_ref: uuid.UUID,
        priority: int = 0,
        due_at: datetime | None = None,
        parent_work_item_id: uuid.UUID | None = None,
        kernel_mode: Literal["native", "legacy_shadow"] = "native",
    ) -> WorkItem:
        if not title:
            raise _fail("WORK_TITLE_INVALID", "/title", "title must not be empty")
        if not 0 <= priority <= 100:
            raise _fail("WORK_PRIORITY_INVALID", "/priority", "priority must be 0..100")
        await self._scope_service._validate_actor(  # noqa: SLF001 - shared application guard
            org_id, created_by_kind, created_by_ref
        )
        scope = await self._session.scalar(
            select(Scope).where(Scope.org_id == org_id, Scope.id == scope_id)
        )
        if scope is None or scope.status != "active":
            raise _fail("SCOPE_NOT_FOUND", "/scope_id", "active scope not found")
        bundle = await self._session.scalar(
            select(DefinitionBundle).where(
                DefinitionBundle.org_id == org_id,
                DefinitionBundle.id == definition_bundle_id,
            )
        )
        if bundle is None:
            raise _fail(
                "DEFINITION_BUNDLE_NOT_FOUND",
                "/definition_bundle_id",
                "definition bundle not found",
            )
        work_definition = self._work_definition(bundle)
        if scope.scope_type not in work_definition.supported_scope_types:
            raise _fail(
                "WORK_SCOPE_TYPE_INVALID",
                "/scope_id",
                f"work definition does not support scope type '{scope.scope_type}'",
            )
        work_definition.input_schema.validate_instance(inputs)

        if parent_work_item_id is not None:
            parent = await self._session.scalar(
                select(WorkItem).where(
                    WorkItem.org_id == org_id,
                    WorkItem.id == parent_work_item_id,
                )
            )
            if parent is None:
                raise _fail(
                    "PARENT_WORK_NOT_FOUND",
                    "/parent_work_item_id",
                    "parent work item not found",
                )
            if parent.scope_id != scope.id:
                raise _fail(
                    "PARENT_WORK_SCOPE_INVALID",
                    "/parent_work_item_id",
                    "parent and child work must share a scope in K1",
                )

        row = WorkItem(
            org_id=org_id,
            scope_id=scope.id,
            parent_work_item_id=parent_work_item_id,
            definition_bundle_id=bundle.id,
            title=title,
            lifecycle_state=work_definition.state_machine.initial_state,
            execution_status="idle",
            inputs=inputs,
            priority=priority,
            due_at=due_at,
            created_by_kind=created_by_kind,
            created_by_ref=created_by_ref,
            version=1,
            input_revision=1,
            kernel_mode=kernel_mode,
            current_plan_id=None,
            active_run_id=None,
            latest_evaluation_id=None,
            closed_at=None,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def bind_responsible_role(
        self,
        *,
        org_id: uuid.UUID,
        work_item_id: uuid.UUID,
        role_slot_key: str,
        responsible_assignment_id: uuid.UUID,
    ) -> WorkRoleBinding:
        work = await self._work(org_id, work_item_id, for_update=True)
        bundle = await self._session.scalar(
            select(DefinitionBundle).where(
                DefinitionBundle.org_id == org_id,
                DefinitionBundle.id == work.definition_bundle_id,
            )
        )
        if bundle is None:  # pragma: no cover - protected by composite FK
            raise _fail("DEFINITION_BUNDLE_NOT_FOUND", "", "definition bundle not found")
        definition = self._work_definition(bundle)
        slot = next((item for item in definition.role_slots if item.key == role_slot_key), None)
        if slot is None:
            raise _fail(
                "ROLE_SLOT_NOT_FOUND",
                "/role_slot_key",
                f"role slot '{role_slot_key}' is not declared",
            )
        role_projection = bundle.compiled_definition["roles_by_slot"].get(role_slot_key)
        if role_projection is None:
            raise _fail(
                "BUNDLE_ROLE_MISSING",
                "/role_slot_key",
                "compiled bundle does not contain the role slot",
            )
        assignment = await self._session.scalar(
            select(ScopeRoleAssignment).where(
                ScopeRoleAssignment.org_id == org_id,
                ScopeRoleAssignment.id == responsible_assignment_id,
                ScopeRoleAssignment.status == "active",
                or_(
                    ScopeRoleAssignment.valid_from.is_(None),
                    ScopeRoleAssignment.valid_from <= datetime.now(UTC),
                ),
                or_(
                    ScopeRoleAssignment.valid_until.is_(None),
                    ScopeRoleAssignment.valid_until > datetime.now(UTC),
                ),
            )
        )
        if assignment is None:
            raise _fail(
                "ASSIGNMENT_MISSING",
                "/responsible_assignment_id",
                "active responsibility assignment not found",
            )
        if (
            str(assignment.role_definition_version_id)
            != role_projection["role_definition_version_id"]
        ):
            raise _fail(
                "ASSIGNMENT_ROLE_MISMATCH",
                "/responsible_assignment_id",
                "assignment role does not match the compiled slot",
            )
        if assignment.actor_kind not in slot.allowed_actor_kinds:
            raise _fail(
                "ASSIGNMENT_ACTOR_KIND_INVALID",
                "/responsible_assignment_id",
                "assignment actor kind is not allowed by the role slot",
            )
        if not await self._assignment_reaches_scope(
            assignment,
            work.scope_id,
            allow_inherited=slot.inheritance_mode != "none",
        ):
            raise _fail(
                "ASSIGNMENT_SCOPE_MISMATCH",
                "/responsible_assignment_id",
                "assignment does not apply to the work scope",
            )
        separated_slots = set(slot.separation_of_duties_from)
        if separated_slots:
            conflicting_actor = await self._session.scalar(
                select(WorkRoleBinding.id)
                .join(
                    ScopeRoleAssignment,
                    ScopeRoleAssignment.id == WorkRoleBinding.responsible_assignment_id,
                )
                .where(
                    WorkRoleBinding.org_id == org_id,
                    WorkRoleBinding.work_item_id == work.id,
                    WorkRoleBinding.role_slot_key.in_(separated_slots),
                    WorkRoleBinding.status == "active",
                    ScopeRoleAssignment.actor_kind == assignment.actor_kind,
                    ScopeRoleAssignment.actor_ref == assignment.actor_ref,
                )
            )
            if conflicting_actor is not None:
                raise _fail(
                    "RESPONSIBILITY_SEPARATION_VIOLATION",
                    "/responsible_assignment_id",
                    "the actor is already responsible for a separated role slot",
                )

        active_count = await self._session.scalar(
            select(func.count())
            .select_from(WorkRoleBinding)
            .where(
                WorkRoleBinding.org_id == org_id,
                WorkRoleBinding.work_item_id == work.id,
                WorkRoleBinding.role_slot_key == role_slot_key,
                WorkRoleBinding.status == "active",
            )
        )
        if (active_count or 0) >= slot.max_assignments:
            raise _fail(
                "ROLE_SLOT_CARDINALITY_EXCEEDED",
                "/role_slot_key",
                "the role slot already has its maximum active assignments",
            )

        row = WorkRoleBinding(
            org_id=org_id,
            work_item_id=work.id,
            role_slot_key=role_slot_key,
            responsible_assignment_id=assignment.id,
            responsibility_kind_snapshot=slot.responsibility_kind,
            executor_kind=None,
            executor_ref=None,
            delegated_by_binding_id=None,
            status="active",
            valid_from=datetime.now(UTC),
            valid_until=None,
            version=1,
        )
        self._session.add(row)
        work.version += 1
        await self._session.flush()
        return row

    async def get_work_item(self, *, org_id: uuid.UUID, work_item_id: uuid.UUID) -> WorkItem:
        return await self._work(org_id, work_item_id)

    async def list_work_items(
        self,
        *,
        org_id: uuid.UUID,
        scope_id: uuid.UUID | None = None,
        execution_status: str | None = None,
    ) -> list[WorkItem]:
        statement = select(WorkItem).where(WorkItem.org_id == org_id)
        if scope_id is not None:
            statement = statement.where(WorkItem.scope_id == scope_id)
        if execution_status is not None:
            statement = statement.where(WorkItem.execution_status == execution_status)
        return list(
            (
                await self._session.scalars(
                    statement.order_by(WorkItem.priority.desc(), WorkItem.created_at, WorkItem.id)
                )
            ).all()
        )

    async def _work(
        self, org_id: uuid.UUID, work_item_id: uuid.UUID, *, for_update: bool = False
    ) -> WorkItem:
        statement = select(WorkItem).where(
            WorkItem.org_id == org_id,
            WorkItem.id == work_item_id,
        )
        if for_update:
            statement = statement.with_for_update()
        row = await self._session.scalar(statement)
        if row is None:
            raise _fail("WORK_ITEM_NOT_FOUND", "/work_item_id", "work item not found")
        return row

    async def _assignment_reaches_scope(
        self,
        assignment: ScopeRoleAssignment,
        target_scope_id: uuid.UUID,
        *,
        allow_inherited: bool,
    ) -> bool:
        if assignment.scope_id == target_scope_id:
            return True
        if not allow_inherited or assignment.inheritance_mode != "descendants":
            return False
        seen: set[uuid.UUID] = set()
        current_id: uuid.UUID | None = target_scope_id
        while current_id is not None and current_id not in seen:
            seen.add(current_id)
            current = await self._session.scalar(
                select(Scope).where(
                    Scope.org_id == assignment.org_id,
                    Scope.id == current_id,
                )
            )
            if current is None:
                return False
            if current.parent_scope_id == assignment.scope_id:
                return True
            current_id = current.parent_scope_id
        return False

    @staticmethod
    def _work_definition(bundle: DefinitionBundle) -> WorkDefinitionV1:
        try:
            raw = bundle.compiled_definition["work_definition"]["definition"]
        except (KeyError, TypeError) as exc:
            raise _fail(
                "BUNDLE_CONTENT_INVALID",
                "/compiled_definition/work_definition",
                "compiled bundle has no work definition",
            ) from exc
        return WorkDefinitionV1.model_validate(raw)


__all__ = ["WorkItemService"]
