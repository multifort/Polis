"""K2-T2 pure policy, authority, fingerprint, and Approval domain tests."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta

import pytest

from polis.modules.kernel.domain.approval import (
    APPROVAL_DECISION_LOCK_ORDER,
    APPROVAL_RESUME_LOCK_ORDER,
    ApprovalSnapshot,
    approval_family_command,
    consume_approval,
    decide_approval,
    expire_approval,
    revoke_approval,
)
from polis.modules.kernel.domain.policy import (
    ActorIdentity,
    AuthorityGrant,
    CommandFingerprintInput,
    PolicyProvenance,
    RoleOccupancy,
    ScopeAssignmentCandidate,
    command_fingerprint,
    evaluate_policies,
    intersect_authority,
    resolve_scope_assignments,
    validate_separation_of_duties,
)
from polis.modules.kernel.errors import KernelProtocolError
from polis.modules.kernel.schemas import (
    AuthorityConstraintsV1,
    PolicyBindingV1,
    RoleAuthorityV1,
)

NOW = datetime(2026, 7, 23, 10, 0, tzinfo=UTC)
REQUESTER = ActorIdentity("human", "requester")
APPROVER = ActorIdentity("human", "approver")
SERVICE = ActorIdentity("service", "kernel-worker")


def _provenance() -> PolicyProvenance:
    return PolicyProvenance(
        org_policy_revision=3,
        org_policy_checksum="a" * 64,
        domain_policy_checksum="b" * 64,
        platform_policy_version="1.0.0",
        interpreter_version="1.0.0",
        kernel_contract_version="3.4",
    )


def _policy(
    key: str,
    decision: str,
    *,
    reason: str,
    roles: list[str] | None = None,
    ttl: int | None = None,
    when: list[dict[str, object]] | None = None,
) -> PolicyBindingV1:
    return PolicyBindingV1.model_validate(
        {
            "key": key,
            "applies_to_commands": ["start_work"],
            "when": when or [],
            "decision": decision,
            "required_role_slots": roles or [],
            "approval_ttl_seconds": ttl,
            "reason_code": reason,
        }
    )


def _policy_context(risk: str = "high") -> dict[str, object]:
    return {
        "command": {"command_type": "start_work", "payload": {"plan_id": "plan-1"}},
        "work": {"inputs": {"risk_level": risk}, "version": 4},
    }


def _approval(
    *,
    family: str = "work",
    status: str = "pending",
    version: int = 1,
    requester: ActorIdentity = REQUESTER,
    resume_mode: str = "automatic",
) -> ApprovalSnapshot:
    fingerprint = command_fingerprint(
        CommandFingerprintInput(
            org_id="org-1",
            command_family="work",
            target_id="work-1",
            definition_id="bundle-1",
            command_type="start_work",
            command_payload={"plan_id": "plan-1", "amount_cents": 100},
            expected_target_state="ready",
            expected_target_version=4,
        )
    )
    return ApprovalSnapshot(
        id="approval-1",
        org_id="org-1",
        command_family=family,  # type: ignore[arg-type]
        target_id="work-1",
        command_type="start_work",
        command_fingerprint=fingerprint,
        expected_target_state="ready",
        expected_target_version=4,
        requested_by=requester,
        required_role_slots=("owner", "reviewer"),
        status=status,  # type: ignore[arg-type]
        approval_purpose="command_policy",
        version=version,
        expires_at=NOW + timedelta(hours=1),
        resume_mode=resume_mode,  # type: ignore[arg-type]
        payload_snapshot={"plan_id": "plan-1", "amount_cents": 100},
    )


def test_policy_merge_is_deny_first_and_preserves_all_matches() -> None:
    bindings = [
        _policy("allow_start", "allow", reason="SAFE_START"),
        _policy(
            "approve_start",
            "require_approval",
            reason="HIGH_RISK",
            roles=["owner"],
            ttl=600,
        ),
        _policy("deny_start", "deny", reason="PLATFORM_DENY"),
    ]

    result = evaluate_policies(
        bindings,
        _policy_context(),
        command_type="start_work",
        selected_policy_keys=[item.key for item in bindings],
        unmatched_decision="deny",
        unmatched_reason_code="NO_POLICY",
        provenance=_provenance(),
    )

    assert result.decision == "deny"
    assert result.reason_codes == ("SAFE_START", "HIGH_RISK", "PLATFORM_DENY")
    assert result.matched_policy_keys == (
        "allow_start",
        "approve_start",
        "deny_start",
    )
    assert result.required_role_slots == ()
    assert result.approval_ttl_seconds is None
    assert result.snapshot["org_policy_revision"] == 3


def test_approval_policy_merge_unions_roles_and_uses_shortest_ttl() -> None:
    bindings = [
        _policy(
            "owner_gate",
            "require_approval",
            reason="OWNER_REQUIRED",
            roles=["owner"],
            ttl=3600,
            when=[
                {
                    "op": "in",
                    "path": "/work/inputs/risk_level",
                    "value": ["high", "critical"],
                }
            ],
        ),
        _policy(
            "review_gate",
            "require_approval",
            reason="REVIEW_REQUIRED",
            roles=["reviewer", "owner"],
            ttl=600,
        ),
    ]
    result = evaluate_policies(
        bindings,
        _policy_context(),
        command_type="start_work",
        selected_policy_keys=["owner_gate", "review_gate"],
        unmatched_decision="deny",
        unmatched_reason_code="NO_POLICY",
        provenance=_provenance(),
    )
    assert result.decision == "require_approval"
    assert result.required_role_slots == ("owner", "reviewer")
    assert result.approval_ttl_seconds == 600


def test_no_matching_policy_is_explicitly_fail_closed() -> None:
    result = evaluate_policies(
        [],
        _policy_context(),
        command_type="start_work",
        selected_policy_keys=[],
        unmatched_decision="deny",
        unmatched_reason_code="UNKNOWN_ACTION",
        provenance=_provenance(),
    )
    assert result.decision == "deny"
    assert result.reason_codes == ("UNKNOWN_ACTION",)

    with pytest.raises(KernelProtocolError, match="unknown policy"):
        evaluate_policies(
            [],
            _policy_context(),
            command_type="start_work",
            selected_policy_keys=["missing"],
            unmatched_decision="deny",
            unmatched_reason_code="UNKNOWN_ACTION",
            provenance=_provenance(),
        )


def test_policy_provenance_and_safe_projection_are_mandatory() -> None:
    with pytest.raises(KernelProtocolError, match="revision"):
        PolicyProvenance(
            org_policy_revision=0,
            org_policy_checksum="a",
            domain_policy_checksum="b",
            platform_policy_version="1",
            interpreter_version="1",
            kernel_contract_version="3.4",
        )
    with pytest.raises(KernelProtocolError, match="policy checksums"):
        PolicyProvenance(
            org_policy_revision=1,
            org_policy_checksum="",
            domain_policy_checksum="b",
            platform_policy_version="1",
            interpreter_version="1",
            kernel_contract_version="3.4",
        )

    unsafe = _policy(
        "unsafe",
        "deny",
        reason="UNSAFE",
        when=[{"op": "exists", "path": "/actor/credentials"}],
    )
    with pytest.raises(KernelProtocolError) as caught:
        evaluate_policies(
            [unsafe],
            _policy_context(),
            command_type="start_work",
            selected_policy_keys=["unsafe"],
            unmatched_decision="deny",
            unmatched_reason_code="NO_POLICY",
            provenance=_provenance(),
        )
    assert caught.value.code == "CONDITION_PATH_FORBIDDEN"


def test_authority_intersection_and_assignment_constraints_never_expand() -> None:
    platform = AuthorityGrant(
        commands=frozenset({"start_work", "cancel_work"}),
        tools=frozenset({"planner", "executor"}),
        data_scopes=frozenset({"work", "scope"}),
        max_risk_level="critical",
        budget_cents=10_000,
    )
    role = AuthorityGrant(
        commands=frozenset({"start_work", "pause_work"}),
        tools=frozenset({"executor"}),
        data_scopes=frozenset({"work"}),
        max_risk_level="high",
        budget_cents=5_000,
    )
    effective = intersect_authority([platform, role])
    assert effective.commands == frozenset({"start_work"})
    assert effective.tools == frozenset({"executor"})
    assert effective.max_risk_level == "high"
    assert effective.budget_cents == 5_000
    assert effective.permits(
        command_type="start_work",
        risk_level="medium",
        budget_cents=4_000,
    )
    assert not effective.permits(
        command_type="start_work",
        risk_level="critical",
        budget_cents=4_000,
    )
    assert intersect_authority([]) == AuthorityGrant()

    role_schema = RoleAuthorityV1.model_validate(
        {
            "commands": ["start_work"],
            "tools": ["executor"],
            "data_scopes": ["work"],
            "max_risk_level": "high",
            "budget_cents": 5_000,
        }
    )
    base = AuthorityGrant.from_role(role_schema)
    unchanged = base.restrict(AuthorityConstraintsV1.model_validate({}))
    assert unchanged == base
    denied = base.restrict(
        AuthorityConstraintsV1.model_validate(
            {
                "commands": [],
                "tools": [],
                "data_scopes": [],
                "max_risk_level": "low",
                "budget_cents": 0,
            }
        )
    )
    assert denied == AuthorityGrant()
    with pytest.raises(KernelProtocolError, match="not declared"):
        base.restrict(AuthorityConstraintsV1.model_validate({"commands": ["delete_everything"]}))


def test_scope_assignment_resolution_obeys_none_nearest_merge_and_validity() -> None:
    candidates = [
        ScopeAssignmentCandidate(
            "exact",
            "target",
            ActorIdentity("human", "a"),
            "none",
            "active",
        ),
        ScopeAssignmentCandidate(
            "parent",
            "parent",
            ActorIdentity("human", "b"),
            "descendants",
            "active",
        ),
        ScopeAssignmentCandidate(
            "root",
            "root",
            ActorIdentity("agent", "c"),
            "descendants",
            "active",
        ),
        ScopeAssignmentCandidate(
            "not-inherited",
            "parent",
            ActorIdentity("human", "d"),
            "none",
            "active",
        ),
        ScopeAssignmentCandidate(
            "expired",
            "target",
            ActorIdentity("human", "e"),
            "none",
            "active",
            valid_until=NOW,
        ),
    ]
    ancestry = ["target", "parent", "root"]
    assert [
        item.assignment_id
        for item in resolve_scope_assignments(
            ancestry=ancestry,
            slot_inheritance_mode="none",
            candidates=candidates,
            observed_at=NOW,
        )
    ] == ["exact"]
    assert [
        item.assignment_id
        for item in resolve_scope_assignments(
            ancestry=ancestry,
            slot_inheritance_mode="nearest",
            candidates=candidates[1:],
            observed_at=NOW,
        )
    ] == ["parent"]
    assert [
        item.assignment_id
        for item in resolve_scope_assignments(
            ancestry=ancestry,
            slot_inheritance_mode="merge",
            candidates=candidates,
            observed_at=NOW,
        )
    ] == ["exact", "parent", "root"]
    with pytest.raises(KernelProtocolError, match="without cycles"):
        resolve_scope_assignments(
            ancestry=["target", "target"],
            slot_inheritance_mode="merge",
            candidates=candidates,
            observed_at=NOW,
        )


def test_separation_of_duties_rejects_same_actor_across_separated_slots() -> None:
    same_actor = ActorIdentity("human", "person-1")
    with pytest.raises(KernelProtocolError, match="separated slots"):
        validate_separation_of_duties(
            [
                RoleOccupancy("producer", "a1", same_actor),
                RoleOccupancy("reviewer", "a2", same_actor),
            ],
            {"reviewer": frozenset({"producer"})},
        )
    validate_separation_of_duties(
        [
            RoleOccupancy("producer", "a1", same_actor),
            RoleOccupancy("reviewer", "a2", ActorIdentity("human", "person-2")),
        ],
        {"reviewer": frozenset({"producer"})},
    )


def test_command_fingerprint_changes_for_every_bound_intent_dimension() -> None:
    base = CommandFingerprintInput(
        org_id="org-1",
        command_family="work",
        target_id="work-1",
        definition_id="bundle-1",
        command_type="start_work",
        command_payload={"recipient": "a@example.com", "amount_cents": 100},
        expected_target_state="ready",
        expected_target_version=4,
    )
    original = command_fingerprint(base)
    variants = [
        replace(base, org_id="org-2"),
        replace(base, target_id="work-2"),
        replace(base, definition_id="bundle-2"),
        replace(base, command_type="cancel_work"),
        replace(
            base,
            command_payload={"recipient": "b@example.com", "amount_cents": 100},
        ),
        replace(base, expected_target_state="working"),
        replace(base, expected_target_version=5),
    ]
    assert len(original) == 64
    assert all(command_fingerprint(item) != original for item in variants)
    assert command_fingerprint(base) == original


@pytest.mark.parametrize("family", ["definition", "scope", "work"])
@pytest.mark.parametrize("action", ["decide", "expire", "revoke"])
def test_approval_commands_are_explicit_per_family(family: str, action: str) -> None:
    assert approval_family_command(family, action).endswith(f"_{family}_approval")  # type: ignore[arg-type]
    assert APPROVAL_DECISION_LOCK_ORDER == ("approval",)
    assert APPROVAL_RESUME_LOCK_ORDER == ("family_target", "approval")


def test_approve_and_reject_are_versioned_and_immutable() -> None:
    approval = _approval()
    approved = decide_approval(
        approval,
        family_command_type="decide_work_approval",
        expected_approval_version=1,
        decision="approve",
        actor=APPROVER,
        actor_role_slots=frozenset({"owner"}),
        occurred_at=NOW,
        current_command_fingerprint=approval.command_fingerprint,
        current_target_state="ready",
        current_target_version=4,
    )
    assert approved.approval.status == "approved"
    assert approved.approval.version == 2
    assert approved.decision.approval_version == 2
    assert approved.resume_required
    assert approval.status == "pending"
    with pytest.raises(FrozenInstanceError):
        approval.version = 3  # type: ignore[misc]

    rejected = decide_approval(
        approval,
        family_command_type="decide_work_approval",
        expected_approval_version=1,
        decision="reject",
        actor=APPROVER,
        actor_role_slots=frozenset({"reviewer"}),
        occurred_at=NOW,
        current_command_fingerprint="0" * 64,
        current_target_state="changed",
        current_target_version=5,
    )
    assert rejected.approval.status == "rejected"
    assert rejected.response_code == "REJECTED"


def test_stale_approve_revokes_without_ever_approving() -> None:
    approval = _approval()
    mutation = decide_approval(
        approval,
        family_command_type="decide_work_approval",
        expected_approval_version=1,
        decision="approve",
        actor=APPROVER,
        actor_role_slots=frozenset({"owner"}),
        occurred_at=NOW,
        current_command_fingerprint="0" * 64,
        current_target_state="ready",
        current_target_version=4,
    )
    assert mutation.approval.status == "revoked"
    assert mutation.response_code == "APPROVAL_STALE"
    assert mutation.decision.requested_action == "approve"
    assert mutation.decision.outcome_status == "revoked"


@pytest.mark.parametrize(
    ("actor", "slots", "code"),
    [
        (REQUESTER, frozenset({"owner"}), "POLICY_DENIED"),
        (APPROVER, frozenset({"observer"}), "ASSIGNMENT_MISSING"),
        (ActorIdentity("agent", "agent-1"), frozenset({"owner"}), "POLICY_DENIED"),
    ],
)
def test_self_approval_assignment_and_nonhuman_approver_are_rejected(
    actor: ActorIdentity,
    slots: frozenset[str],
    code: str,
) -> None:
    approval = _approval()
    with pytest.raises(KernelProtocolError) as caught:
        decide_approval(
            approval,
            family_command_type="decide_work_approval",
            expected_approval_version=1,
            decision="approve",
            actor=actor,
            actor_role_slots=slots,
            occurred_at=NOW,
            current_command_fingerprint=approval.command_fingerprint,
            current_target_state="ready",
            current_target_version=4,
        )
    assert caught.value.code == code


def test_approval_version_family_and_expiry_guards_precede_mutation() -> None:
    approval = _approval()
    with pytest.raises(KernelProtocolError) as version:
        decide_approval(
            approval,
            family_command_type="decide_work_approval",
            expected_approval_version=2,
            decision="approve",
            actor=APPROVER,
            actor_role_slots=frozenset({"owner"}),
            occurred_at=NOW,
            current_command_fingerprint=approval.command_fingerprint,
            current_target_state="ready",
            current_target_version=4,
        )
    assert version.value.code == "APPROVAL_VERSION_CONFLICT"

    with pytest.raises(KernelProtocolError, match="belongs to work"):
        decide_approval(
            approval,
            family_command_type="decide_scope_approval",
            expected_approval_version=1,
            decision="approve",
            actor=APPROVER,
            actor_role_slots=frozenset({"owner"}),
            occurred_at=NOW,
            current_command_fingerprint=approval.command_fingerprint,
            current_target_state="ready",
            current_target_version=4,
        )

    expired = replace(approval, expires_at=NOW)
    with pytest.raises(KernelProtocolError) as caught:
        decide_approval(
            expired,
            family_command_type="decide_work_approval",
            expected_approval_version=1,
            decision="approve",
            actor=APPROVER,
            actor_role_slots=frozenset({"owner"}),
            occurred_at=NOW,
            current_command_fingerprint=approval.command_fingerprint,
            current_target_state="ready",
            current_target_version=4,
        )
    assert caught.value.code == "APPROVAL_EXPIRED"


def test_expire_and_revoke_follow_closed_state_machine() -> None:
    approval = _approval()
    with pytest.raises(KernelProtocolError, match="not due"):
        expire_approval(
            approval,
            family_command_type="expire_work_approval",
            expected_approval_version=1,
            service_actor=SERVICE,
            transaction_time=NOW,
            reason="TTL",
        )
    expired = expire_approval(
        approval,
        family_command_type="expire_work_approval",
        expected_approval_version=1,
        service_actor=SERVICE,
        transaction_time=approval.expires_at,
        reason="TTL",
    )
    assert expired.approval.status == "expired"
    assert expired.approval.version == 2

    revoked = revoke_approval(
        approval,
        family_command_type="revoke_work_approval",
        expected_approval_version=1,
        actor=SERVICE,
        occurred_at=NOW,
        reason="TARGET_CHANGED",
    )
    assert revoked.approval.status == "revoked"
    with pytest.raises(KernelProtocolError, match="cannot revoke"):
        revoke_approval(
            expired.approval,
            family_command_type="revoke_work_approval",
            expected_approval_version=2,
            actor=SERVICE,
            occurred_at=NOW,
            reason="AGAIN",
        )


def test_approved_intent_consumes_once_or_revokes_when_stale() -> None:
    pending = _approval()
    approved = decide_approval(
        pending,
        family_command_type="decide_work_approval",
        expected_approval_version=1,
        decision="approve",
        actor=APPROVER,
        actor_role_slots=frozenset({"owner"}),
        occurred_at=NOW,
        current_command_fingerprint=pending.command_fingerprint,
        current_target_state="ready",
        current_target_version=4,
    ).approval
    consumed = consume_approval(
        approved,
        expected_approval_version=2,
        command_id="command-1",
        command_fingerprint=approved.command_fingerprint,
        current_target_state="ready",
        current_target_version=4,
        service_actor=SERVICE,
        occurred_at=NOW + timedelta(minutes=1),
    )
    assert consumed.approval.status == "consumed"
    assert consumed.approval.consumed_by_command_id == "command-1"
    with pytest.raises(KernelProtocolError, match="only approved"):
        consume_approval(
            consumed.approval,
            expected_approval_version=3,
            command_id="command-2",
            command_fingerprint=approved.command_fingerprint,
            current_target_state="ready",
            current_target_version=4,
            service_actor=SERVICE,
            occurred_at=NOW + timedelta(minutes=2),
        )

    stale = consume_approval(
        approved,
        expected_approval_version=2,
        command_id="command-3",
        command_fingerprint=approved.command_fingerprint,
        current_target_state="ready",
        current_target_version=5,
        service_actor=SERVICE,
        occurred_at=NOW + timedelta(minutes=1),
    )
    assert stale.approval.status == "revoked"
    assert stale.response_code == "APPROVAL_STALE"
