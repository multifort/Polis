"""Shared persistence boundary for family-owned Approval V2 mutations."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from polis.modules.kernel.domain.approval import (
    ApprovalMutation,
    ApprovalSnapshot,
)
from polis.modules.kernel.domain.policy import ActorIdentity, CommandFamily
from polis.modules.kernel.errors import KernelProtocolError
from polis.modules.kernel.models import Approval, ApprovalDecision


class ApprovalMutationStore:
    """Lock and stage Approval changes without choosing a command family or committing."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def lock_v2(
        self,
        *,
        org_id: uuid.UUID,
        approval_id: uuid.UUID,
    ) -> Approval:
        row = await self._session.scalar(
            select(Approval)
            .where(
                Approval.org_id == org_id,
                Approval.id == approval_id,
                Approval.approval_schema_version == 2,
            )
            .with_for_update()
        )
        if row is None:
            raise KernelProtocolError(
                "APPROVAL_INVALID",
                "/approval_id",
                "Approval V2 was not found in this organization",
            )
        return row

    @staticmethod
    def snapshot(
        row: Approval,
        *,
        expected_target_state: str | None = None,
        expected_target_version: int | None = None,
    ) -> ApprovalSnapshot:
        required = {
            "command_family": row.command_family,
            "command_type": row.command_type,
            "command_fingerprint": row.command_fingerprint,
            "approval_purpose": row.approval_purpose,
            "version": row.version,
            "requested_by_kind": row.requested_by_kind,
            "requested_by_ref": row.requested_by_ref,
            "required_role_slots": row.required_role_slots,
            "expires_at": row.expires_at,
            "resume_mode": row.resume_mode,
            "payload_snapshot": row.payload_snapshot,
        }
        missing = sorted(key for key, value in required.items() if value is None)
        if row.approval_schema_version != 2 or missing:
            raise KernelProtocolError(
                "APPROVAL_INVALID",
                "/approval",
                f"Approval V2 snapshot is incomplete; missing={missing}",
            )
        target_id = ApprovalMutationStore._target_id(row)
        return ApprovalSnapshot(
            id=str(row.id),
            org_id=str(row.org_id),
            command_family=cast(CommandFamily, row.command_family),
            target_id=str(target_id),
            command_type=cast(str, row.command_type),
            command_fingerprint=cast(str, row.command_fingerprint),
            expected_target_state=expected_target_state,
            expected_target_version=expected_target_version,
            requested_by=ActorIdentity(
                cast(Literal["human", "agent", "service"], row.requested_by_kind),
                str(row.requested_by_ref),
            ),
            required_role_slots=tuple(cast(list[str], row.required_role_slots)),
            status=cast(
                Literal[
                    "pending",
                    "approved",
                    "rejected",
                    "expired",
                    "revoked",
                    "consumed",
                ],
                row.status,
            ),
            approval_purpose=cast(
                Literal["command_policy", "execution_gate", "quality_review"],
                row.approval_purpose,
            ),
            version=cast(int, row.version),
            expires_at=cast(datetime, row.expires_at),
            resume_mode=cast(Literal["manual", "automatic"], row.resume_mode),
            payload_snapshot=dict(cast(dict[str, object], row.payload_snapshot)),
            decided_by=(
                ActorIdentity(
                    cast(Literal["human", "agent", "service"], row.decided_by_kind),
                    str(row.decided_by_ref),
                )
                if row.decided_by_kind is not None and row.decided_by_ref is not None
                else None
            ),
            decided_at=row.decided_at,
            decision_reason=row.decision_reason,
            consumed_by_command_id=(
                str(row.consumed_by_command_id) if row.consumed_by_command_id is not None else None
            ),
        )

    async def stage(
        self,
        *,
        row: Approval,
        mutation: ApprovalMutation,
        family_command_id: uuid.UUID,
    ) -> ApprovalDecision:
        expected_previous_version = mutation.approval.version - 1
        if (
            str(row.id) != mutation.approval.id
            or str(row.org_id) != mutation.approval.org_id
            or row.version != expected_previous_version
        ):
            raise KernelProtocolError(
                "APPROVAL_VERSION_CONFLICT",
                "/expected_approval_version",
                "locked Approval changed before mutation persistence",
            )
        row.status = mutation.approval.status
        row.version = mutation.approval.version
        row.decided_by_kind = (
            mutation.approval.decided_by.kind if mutation.approval.decided_by is not None else None
        )
        row.decided_by_ref = (
            uuid.UUID(mutation.approval.decided_by.ref)
            if mutation.approval.decided_by is not None
            else None
        )
        row.decided_at = mutation.approval.decided_at
        row.decision_reason = mutation.approval.decision_reason
        row.consumed_by_command_id = (
            uuid.UUID(mutation.approval.consumed_by_command_id)
            if mutation.approval.consumed_by_command_id is not None
            else None
        )
        decision = ApprovalDecision(
            org_id=row.org_id,
            approval_id=row.id,
            approval_version=mutation.decision.approval_version,
            family_command_id=family_command_id,
            requested_action=mutation.decision.requested_action,
            outcome_status=mutation.decision.outcome_status,
            decided_by_kind=mutation.decision.decided_by.kind,
            decided_by_ref=uuid.UUID(mutation.decision.decided_by.ref),
            reason_code=mutation.decision.reason_code,
            reason_note=mutation.decision.reason_note,
            occurred_at=mutation.decision.occurred_at,
        )
        self._session.add(decision)
        await self._session.flush()
        return decision

    @staticmethod
    def _target_id(row: Approval) -> uuid.UUID:
        targets = [
            target
            for target in (
                row.domain_package_version_id,
                row.work_definition_version_id,
                row.role_definition_version_id,
                row.scope_id,
                row.work_item_id,
            )
            if target is not None
        ]
        if len(targets) != 1:
            raise KernelProtocolError(
                "APPROVAL_INVALID",
                "/approval",
                "Approval V2 must have exactly one explicit family target",
            )
        return targets[0]


__all__ = ["ApprovalMutationStore"]
