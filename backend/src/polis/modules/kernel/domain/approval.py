"""Pure Approval V2 state machine owned by the three kernel command families."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Literal

from polis.modules.kernel.domain.policy import ActorIdentity, CommandFamily
from polis.modules.kernel.errors import KernelProtocolError

type ApprovalStatus = Literal[
    "pending",
    "approved",
    "rejected",
    "expired",
    "revoked",
    "consumed",
]
type ApprovalPurpose = Literal["command_policy", "execution_gate", "quality_review"]
type ResumeMode = Literal["manual", "automatic"]
type Decision = Literal["approve", "reject"]
type ApprovalAction = Literal["decide", "expire", "revoke"]

_FAMILY_COMMANDS: dict[tuple[CommandFamily, ApprovalAction], str] = {
    ("definition", "decide"): "decide_definition_approval",
    ("definition", "expire"): "expire_definition_approval",
    ("definition", "revoke"): "revoke_definition_approval",
    ("scope", "decide"): "decide_scope_approval",
    ("scope", "expire"): "expire_scope_approval",
    ("scope", "revoke"): "revoke_scope_approval",
    ("work", "decide"): "decide_work_approval",
    ("work", "expire"): "expire_work_approval",
    ("work", "revoke"): "revoke_work_approval",
}

APPROVAL_DECISION_LOCK_ORDER = ("approval",)
APPROVAL_RESUME_LOCK_ORDER = ("family_target", "approval")


@dataclass(frozen=True, slots=True)
class ApprovalSnapshot:
    id: str
    org_id: str
    command_family: CommandFamily
    target_id: str
    command_type: str
    command_fingerprint: str
    expected_target_state: str | None
    expected_target_version: int | None
    requested_by: ActorIdentity
    required_role_slots: tuple[str, ...]
    status: ApprovalStatus
    approval_purpose: ApprovalPurpose
    version: int
    expires_at: datetime
    resume_mode: ResumeMode
    payload_snapshot: dict[str, Any]
    decided_by: ActorIdentity | None = None
    decided_at: datetime | None = None
    decision_reason: str | None = None
    consumed_by_command_id: str | None = None

    def __post_init__(self) -> None:
        if any(
            not value
            for value in (
                self.id,
                self.org_id,
                self.target_id,
                self.command_type,
                self.command_fingerprint,
            )
        ):
            raise ValueError("Approval identity fields must not be empty")
        if len(self.command_fingerprint) != 64 or any(
            character not in "0123456789abcdef" for character in self.command_fingerprint
        ):
            raise ValueError("command_fingerprint must be SHA-256 hex")
        if self.version < 1:
            raise ValueError("Approval version must be positive")
        if not self.required_role_slots:
            raise ValueError("Approval requires at least one role slot")


@dataclass(frozen=True, slots=True)
class ApprovalDecision:
    approval_id: str
    approval_version: int
    family_command_type: str
    requested_action: Literal["approve", "reject", "expire", "revoke", "consume"]
    outcome_status: Literal["approved", "rejected", "expired", "revoked", "consumed"]
    decided_by: ActorIdentity
    reason_code: str | None
    reason_note: str | None
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class ApprovalMutation:
    approval: ApprovalSnapshot
    decision: ApprovalDecision
    response_code: str
    resume_required: bool


def approval_family_command(
    family: CommandFamily,
    action: ApprovalAction,
) -> str:
    return _FAMILY_COMMANDS[(family, action)]


def _assert_family_command(
    approval: ApprovalSnapshot,
    *,
    action: ApprovalAction,
    family_command_type: str,
) -> None:
    expected = approval_family_command(approval.command_family, action)
    if family_command_type != expected:
        raise KernelProtocolError(
            "APPROVAL_INVALID",
            "/command/command_type",
            f"Approval belongs to {approval.command_family}; expected '{expected}'",
        )


def _assert_version(
    approval: ApprovalSnapshot,
    expected_approval_version: int,
) -> None:
    if approval.version != expected_approval_version:
        raise KernelProtocolError(
            "APPROVAL_VERSION_CONFLICT",
            "/expected_approval_version",
            f"expected Approval version {expected_approval_version}, found {approval.version}",
        )


def _assert_pending(approval: ApprovalSnapshot) -> None:
    if approval.status != "pending":
        raise KernelProtocolError(
            "APPROVAL_INVALID",
            "/approval/status",
            f"Approval is already {approval.status}",
        )


def _assert_approver(
    approval: ApprovalSnapshot,
    *,
    actor: ActorIdentity,
    actor_role_slots: frozenset[str],
    allow_self_approval: bool,
) -> None:
    if actor.kind != "human":
        raise KernelProtocolError(
            "POLICY_DENIED",
            "/actor/kind",
            "only a human actor can decide an Approval",
        )
    if not actor_role_slots.intersection(approval.required_role_slots):
        raise KernelProtocolError(
            "ASSIGNMENT_MISSING",
            "/approval/required_role_slots",
            "approver does not occupy an eligible role slot",
        )
    if not allow_self_approval and actor == approval.requested_by:
        raise KernelProtocolError(
            "POLICY_DENIED",
            "/actor/ref",
            "Approval requester cannot approve their own command",
        )


def _decision(
    approval: ApprovalSnapshot,
    *,
    family_command_type: str,
    requested_action: Literal["approve", "reject", "expire", "revoke", "consume"],
    outcome_status: Literal["approved", "rejected", "expired", "revoked", "consumed"],
    actor: ActorIdentity,
    reason_code: str | None,
    reason_note: str | None,
    occurred_at: datetime,
) -> ApprovalDecision:
    return ApprovalDecision(
        approval_id=approval.id,
        approval_version=approval.version,
        family_command_type=family_command_type,
        requested_action=requested_action,
        outcome_status=outcome_status,
        decided_by=actor,
        reason_code=reason_code,
        reason_note=reason_note,
        occurred_at=occurred_at,
    )


def decide_approval(
    approval: ApprovalSnapshot,
    *,
    family_command_type: str,
    expected_approval_version: int,
    decision: Decision,
    actor: ActorIdentity,
    actor_role_slots: frozenset[str],
    occurred_at: datetime,
    current_command_fingerprint: str,
    current_target_state: str | None,
    current_target_version: int | None,
    reason: str | None = None,
    allow_self_approval: bool = False,
) -> ApprovalMutation:
    """Approve/reject a pending intent; stale approve revokes without an approved state."""

    _assert_family_command(
        approval,
        action="decide",
        family_command_type=family_command_type,
    )
    _assert_version(approval, expected_approval_version)
    _assert_pending(approval)
    _assert_approver(
        approval,
        actor=actor,
        actor_role_slots=actor_role_slots,
        allow_self_approval=allow_self_approval,
    )
    if occurred_at >= approval.expires_at:
        raise KernelProtocolError(
            "APPROVAL_EXPIRED",
            "/approval/expires_at",
            "Approval has expired and must be expired by its family command",
        )

    stale = (
        current_command_fingerprint != approval.command_fingerprint
        or current_target_state != approval.expected_target_state
        or current_target_version != approval.expected_target_version
    )
    if decision == "approve" and stale:
        changed = replace(
            approval,
            status="revoked",
            version=approval.version + 1,
            decided_by=actor,
            decided_at=occurred_at,
            decision_reason=reason,
        )
        return ApprovalMutation(
            approval=changed,
            decision=_decision(
                changed,
                family_command_type=family_command_type,
                requested_action="approve",
                outcome_status="revoked",
                actor=actor,
                reason_code="APPROVAL_STALE",
                reason_note=reason,
                occurred_at=occurred_at,
            ),
            response_code="APPROVAL_STALE",
            resume_required=False,
        )

    next_status: ApprovalStatus = "approved" if decision == "approve" else "rejected"
    changed = replace(
        approval,
        status=next_status,
        version=approval.version + 1,
        decided_by=actor,
        decided_at=occurred_at,
        decision_reason=reason,
    )
    return ApprovalMutation(
        approval=changed,
        decision=_decision(
            changed,
            family_command_type=family_command_type,
            requested_action=decision,
            outcome_status="approved" if decision == "approve" else "rejected",
            actor=actor,
            reason_code=None,
            reason_note=reason,
            occurred_at=occurred_at,
        ),
        response_code="APPROVED" if decision == "approve" else "REJECTED",
        resume_required=decision == "approve" and approval.resume_mode == "automatic",
    )


def expire_approval(
    approval: ApprovalSnapshot,
    *,
    family_command_type: str,
    expected_approval_version: int,
    service_actor: ActorIdentity,
    transaction_time: datetime,
    reason: str,
) -> ApprovalMutation:
    """Expire only a pending Approval using the database transaction timestamp."""

    _assert_family_command(
        approval,
        action="expire",
        family_command_type=family_command_type,
    )
    _assert_version(approval, expected_approval_version)
    _assert_pending(approval)
    if transaction_time < approval.expires_at:
        raise KernelProtocolError(
            "APPROVAL_INVALID",
            "/approval/expires_at",
            "Approval is not due for expiry",
        )
    changed = replace(
        approval,
        status="expired",
        version=approval.version + 1,
        decided_by=service_actor,
        decided_at=transaction_time,
        decision_reason=reason,
    )
    return ApprovalMutation(
        approval=changed,
        decision=_decision(
            changed,
            family_command_type=family_command_type,
            requested_action="expire",
            outcome_status="expired",
            actor=service_actor,
            reason_code=reason,
            reason_note=None,
            occurred_at=transaction_time,
        ),
        response_code="APPROVAL_EXPIRED",
        resume_required=False,
    )


def revoke_approval(
    approval: ApprovalSnapshot,
    *,
    family_command_type: str,
    expected_approval_version: int,
    actor: ActorIdentity,
    occurred_at: datetime,
    reason: str,
) -> ApprovalMutation:
    """Revoke a pending or approved Approval without locking its target."""

    _assert_family_command(
        approval,
        action="revoke",
        family_command_type=family_command_type,
    )
    _assert_version(approval, expected_approval_version)
    if approval.status not in {"pending", "approved"}:
        raise KernelProtocolError(
            "APPROVAL_INVALID",
            "/approval/status",
            f"cannot revoke an Approval in status '{approval.status}'",
        )
    changed = replace(
        approval,
        status="revoked",
        version=approval.version + 1,
        decided_by=actor,
        decided_at=occurred_at,
        decision_reason=reason,
    )
    return ApprovalMutation(
        approval=changed,
        decision=_decision(
            changed,
            family_command_type=family_command_type,
            requested_action="revoke",
            outcome_status="revoked",
            actor=actor,
            reason_code=reason,
            reason_note=None,
            occurred_at=occurred_at,
        ),
        response_code="APPROVAL_STALE",
        resume_required=False,
    )


def consume_approval(
    approval: ApprovalSnapshot,
    *,
    expected_approval_version: int,
    command_id: str,
    command_fingerprint: str,
    current_target_state: str | None,
    current_target_version: int | None,
    service_actor: ActorIdentity,
    occurred_at: datetime,
) -> ApprovalMutation:
    """Consume one approved intent once, or revoke it when the target became stale."""

    _assert_version(approval, expected_approval_version)
    if approval.status != "approved":
        raise KernelProtocolError(
            "APPROVAL_INVALID",
            "/approval/status",
            f"only approved intents can be consumed; found '{approval.status}'",
        )
    stale = (
        occurred_at >= approval.expires_at
        or command_fingerprint != approval.command_fingerprint
        or current_target_state != approval.expected_target_state
        or current_target_version != approval.expected_target_version
    )
    if stale:
        changed = replace(
            approval,
            status="revoked",
            version=approval.version + 1,
            decided_by=service_actor,
            decided_at=occurred_at,
            decision_reason="approval intent became stale before consumption",
        )
        return ApprovalMutation(
            approval=changed,
            decision=_decision(
                changed,
                family_command_type=approval.command_type,
                requested_action="consume",
                outcome_status="revoked",
                actor=service_actor,
                reason_code="APPROVAL_STALE",
                reason_note=None,
                occurred_at=occurred_at,
            ),
            response_code="APPROVAL_STALE",
            resume_required=False,
        )
    changed = replace(
        approval,
        status="consumed",
        version=approval.version + 1,
        consumed_by_command_id=command_id,
    )
    return ApprovalMutation(
        approval=changed,
        decision=_decision(
            changed,
            family_command_type=approval.command_type,
            requested_action="consume",
            outcome_status="consumed",
            actor=service_actor,
            reason_code=None,
            reason_note=None,
            occurred_at=occurred_at,
        ),
        response_code="APPROVAL_CONSUMED",
        resume_required=False,
    )


__all__ = [
    "APPROVAL_DECISION_LOCK_ORDER",
    "APPROVAL_RESUME_LOCK_ORDER",
    "ApprovalAction",
    "ApprovalDecision",
    "ApprovalMutation",
    "ApprovalPurpose",
    "ApprovalSnapshot",
    "ApprovalStatus",
    "Decision",
    "ResumeMode",
    "approval_family_command",
    "consume_approval",
    "decide_approval",
    "expire_approval",
    "revoke_approval",
]
