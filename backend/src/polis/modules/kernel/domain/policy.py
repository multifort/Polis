"""Deterministic policy, authority, scope-resolution, and fingerprint primitives."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from polis.modules.kernel.domain.canonical import canonical_checksum
from polis.modules.kernel.domain.expressions import ConditionFacts, evaluate_condition
from polis.modules.kernel.domain.state_machine import validate_guard_conditions
from polis.modules.kernel.errors import KernelProtocolError
from polis.modules.kernel.schemas import (
    AuthorityConstraintsV1,
    PolicyBindingV1,
    RoleAuthorityV1,
)

type PolicyDecision = Literal["allow", "deny", "require_approval"]
type RiskLevel = Literal["low", "medium", "high", "critical"]
type CommandFamily = Literal["definition", "scope", "work"]
type ActorKind = Literal["human", "agent", "service"]
type SlotInheritanceMode = Literal["none", "nearest", "merge"]
type AssignmentInheritanceMode = Literal["none", "descendants"]

_RISK_ORDER: Mapping[RiskLevel, int] = {
    "low": 0,
    "medium": 1,
    "high": 2,
    "critical": 3,
}
_RISK_BY_ORDER = {value: key for key, value in _RISK_ORDER.items()}


@dataclass(frozen=True, slots=True)
class ActorIdentity:
    kind: ActorKind
    ref: str

    def __post_init__(self) -> None:
        if not self.ref:
            raise ValueError("actor ref must not be empty")


@dataclass(frozen=True, slots=True)
class AuthorityGrant:
    """One explicit maximum-authority layer."""

    commands: frozenset[str] = field(default_factory=frozenset)
    tools: frozenset[str] = field(default_factory=frozenset)
    data_scopes: frozenset[str] = field(default_factory=frozenset)
    max_risk_level: RiskLevel = "low"
    budget_cents: int = 0

    def __post_init__(self) -> None:
        if self.budget_cents < 0:
            raise ValueError("budget_cents must not be negative")

    @classmethod
    def from_role(cls, authority: RoleAuthorityV1) -> AuthorityGrant:
        return cls(
            commands=frozenset(authority.commands),
            tools=frozenset(authority.tools),
            data_scopes=frozenset(authority.data_scopes),
            max_risk_level=authority.max_risk_level,
            budget_cents=authority.budget_cents,
        )

    def restrict(self, constraints: AuthorityConstraintsV1) -> AuthorityGrant:
        constraints.validate_subset_of(
            RoleAuthorityV1.model_validate(
                {
                    "commands": sorted(self.commands),
                    "tools": sorted(self.tools),
                    "data_scopes": sorted(self.data_scopes),
                    "max_risk_level": self.max_risk_level,
                    "budget_cents": self.budget_cents,
                }
            )
        )
        return AuthorityGrant(
            commands=(
                self.commands
                if constraints.commands is None
                else self.commands.intersection(constraints.commands)
            ),
            tools=(
                self.tools
                if constraints.tools is None
                else self.tools.intersection(constraints.tools)
            ),
            data_scopes=(
                self.data_scopes
                if constraints.data_scopes is None
                else self.data_scopes.intersection(constraints.data_scopes)
            ),
            max_risk_level=(
                self.max_risk_level
                if constraints.max_risk_level is None
                else _minimum_risk(self.max_risk_level, constraints.max_risk_level)
            ),
            budget_cents=(
                self.budget_cents
                if constraints.budget_cents is None
                else min(self.budget_cents, constraints.budget_cents)
            ),
        )

    def permits(
        self,
        *,
        command_type: str,
        risk_level: RiskLevel,
        budget_cents: int,
    ) -> bool:
        return (
            command_type in self.commands
            and _RISK_ORDER[risk_level] <= _RISK_ORDER[self.max_risk_level]
            and budget_cents <= self.budget_cents
        )


def _minimum_risk(left: RiskLevel, right: RiskLevel) -> RiskLevel:
    return _RISK_BY_ORDER[min(_RISK_ORDER[left], _RISK_ORDER[right])]


def intersect_authority(layers: Sequence[AuthorityGrant]) -> AuthorityGrant:
    """Intersect explicit layers; a missing chain is fail-closed."""

    if not layers:
        return AuthorityGrant()
    current = layers[0]
    for layer in layers[1:]:
        current = AuthorityGrant(
            commands=current.commands.intersection(layer.commands),
            tools=current.tools.intersection(layer.tools),
            data_scopes=current.data_scopes.intersection(layer.data_scopes),
            max_risk_level=_minimum_risk(
                current.max_risk_level,
                layer.max_risk_level,
            ),
            budget_cents=min(current.budget_cents, layer.budget_cents),
        )
    return current


@dataclass(frozen=True, slots=True)
class ScopeAssignmentCandidate:
    assignment_id: str
    scope_id: str
    actor: ActorIdentity
    inheritance_mode: AssignmentInheritanceMode
    status: Literal["pending", "active", "suspended", "ended"]
    valid_from: datetime | None = None
    valid_until: datetime | None = None

    def __post_init__(self) -> None:
        if not self.assignment_id or not self.scope_id:
            raise ValueError("assignment and scope IDs must not be empty")

    def is_active_at(self, observed_at: datetime) -> bool:
        return (
            self.status == "active"
            and (self.valid_from is None or self.valid_from <= observed_at)
            and (self.valid_until is None or observed_at < self.valid_until)
        )


def resolve_scope_assignments(
    *,
    ancestry: Sequence[str],
    slot_inheritance_mode: SlotInheritanceMode,
    candidates: Sequence[ScopeAssignmentCandidate],
    observed_at: datetime,
) -> tuple[ScopeAssignmentCandidate, ...]:
    """Resolve exact/nearest/merge assignments against target-to-root ancestry."""

    if not ancestry or len(ancestry) != len(set(ancestry)):
        raise KernelProtocolError(
            "SCOPE_RELATION_INVALID",
            "/scope/ancestry",
            "ancestry must be a non-empty target-to-root chain without cycles",
        )
    distances = {scope_id: index for index, scope_id in enumerate(ancestry)}
    eligible = [
        candidate
        for candidate in candidates
        if candidate.scope_id in distances
        and candidate.is_active_at(observed_at)
        and (distances[candidate.scope_id] == 0 or candidate.inheritance_mode == "descendants")
    ]
    if slot_inheritance_mode == "none":
        eligible = [candidate for candidate in eligible if distances[candidate.scope_id] == 0]
    elif slot_inheritance_mode == "nearest" and eligible:
        nearest = min(distances[candidate.scope_id] for candidate in eligible)
        eligible = [candidate for candidate in eligible if distances[candidate.scope_id] == nearest]
    return tuple(
        sorted(
            eligible,
            key=lambda candidate: (
                distances[candidate.scope_id],
                candidate.assignment_id,
            ),
        )
    )


@dataclass(frozen=True, slots=True)
class RoleOccupancy:
    slot_key: str
    assignment_id: str
    actor: ActorIdentity


def validate_separation_of_duties(
    occupancies: Sequence[RoleOccupancy],
    separation_by_slot: Mapping[str, frozenset[str]],
) -> None:
    """Reject the same actor occupying any declared separated slot pair."""

    by_slot: dict[str, list[RoleOccupancy]] = {}
    for occupancy in occupancies:
        by_slot.setdefault(occupancy.slot_key, []).append(occupancy)
    for slot_key, separated_slots in separation_by_slot.items():
        for left in by_slot.get(slot_key, []):
            for separated_slot in separated_slots:
                for right in by_slot.get(separated_slot, []):
                    if left.actor == right.actor:
                        raise KernelProtocolError(
                            "ASSIGNMENT_STATE_INVALID",
                            f"/role_slots/{slot_key}/separation_of_duties_from",
                            f"actor occupies separated slots '{slot_key}' and '{separated_slot}'",
                        )


@dataclass(frozen=True, slots=True)
class PolicyProvenance:
    org_policy_revision: int
    org_policy_checksum: str
    domain_policy_checksum: str
    platform_policy_version: str
    interpreter_version: str
    kernel_contract_version: str

    def __post_init__(self) -> None:
        if self.org_policy_revision < 1:
            raise KernelProtocolError(
                "GOVERNANCE_SCOPE_MISSING",
                "/policy_snapshot/org_policy_revision",
                "organization policy revision must be positive",
            )
        if not _is_checksum(self.org_policy_checksum) or not _is_checksum(
            self.domain_policy_checksum
        ):
            raise KernelProtocolError(
                "GOVERNANCE_SCOPE_MISSING",
                "/policy_snapshot",
                "policy checksums must be 64-character lower-case SHA-256 hex",
            )
        versions = (
            self.platform_policy_version,
            self.interpreter_version,
            self.kernel_contract_version,
        )
        if any(not value for value in versions):
            raise KernelProtocolError(
                "GOVERNANCE_SCOPE_MISSING",
                "/policy_snapshot",
                "complete policy version provenance is required",
            )


@dataclass(frozen=True, slots=True)
class MatchedPolicy:
    policy_key: str
    decision: PolicyDecision
    reason_code: str
    required_role_slots: tuple[str, ...]
    approval_ttl_seconds: int | None


@dataclass(frozen=True, slots=True)
class PolicyEvaluation:
    decision: PolicyDecision
    reason_codes: tuple[str, ...]
    matched_policy_keys: tuple[str, ...]
    required_role_slots: tuple[str, ...]
    approval_ttl_seconds: int | None
    matched: tuple[MatchedPolicy, ...]
    provenance: PolicyProvenance

    @property
    def snapshot(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "reason_codes": list(self.reason_codes),
            "matched_policy_keys": list(self.matched_policy_keys),
            "required_role_slots": list(self.required_role_slots),
            "approval_ttl_seconds": self.approval_ttl_seconds,
            "org_policy_revision": self.provenance.org_policy_revision,
            "org_policy_checksum": self.provenance.org_policy_checksum,
            "domain_policy_checksum": self.provenance.domain_policy_checksum,
            "platform_policy_version": self.provenance.platform_policy_version,
            "policy_interpreter_version": self.provenance.interpreter_version,
            "kernel_contract_version": self.provenance.kernel_contract_version,
        }


def evaluate_policies(
    bindings: Sequence[PolicyBindingV1],
    context: Mapping[str, Any],
    *,
    command_type: str,
    selected_policy_keys: Sequence[str],
    unmatched_decision: PolicyDecision,
    unmatched_reason_code: str,
    provenance: PolicyProvenance,
    facts: ConditionFacts | None = None,
) -> PolicyEvaluation:
    """Evaluate selected bindings and merge every match with deny-first precedence."""

    by_key = {binding.key: binding for binding in bindings}
    unknown = sorted(set(selected_policy_keys) - set(by_key))
    if unknown:
        raise KernelProtocolError(
            "BUNDLE_INCOMPATIBLE",
            "/policy_keys",
            f"unknown policy keys {unknown}",
        )
    matched: list[MatchedPolicy] = []
    for policy_key in selected_policy_keys:
        binding = by_key[policy_key]
        if command_type not in binding.applies_to_commands:
            continue
        validate_guard_conditions(
            binding.when,
            path=f"/policy_bindings/{binding.key}/when",
        )
        if all(
            evaluate_condition(condition, context, usage="policy", facts=facts)
            for condition in binding.when
        ):
            matched.append(
                MatchedPolicy(
                    policy_key=binding.key,
                    decision=binding.decision,
                    reason_code=binding.reason_code,
                    required_role_slots=tuple(binding.required_role_slots),
                    approval_ttl_seconds=binding.approval_ttl_seconds,
                )
            )

    if any(item.decision == "deny" for item in matched):
        decision: PolicyDecision = "deny"
    elif any(item.decision == "require_approval" for item in matched):
        decision = "require_approval"
    elif matched:
        decision = "allow"
    else:
        decision = unmatched_decision

    reason_codes = _ordered_unique(
        [item.reason_code for item in matched] or [unmatched_reason_code]
    )
    matched_keys = tuple(item.policy_key for item in matched)
    approval_items = [item for item in matched if item.decision == "require_approval"]
    required_slots = _ordered_unique(
        slot for item in approval_items for slot in item.required_role_slots
    )
    ttl_values = [
        item.approval_ttl_seconds
        for item in approval_items
        if item.approval_ttl_seconds is not None
    ]
    return PolicyEvaluation(
        decision=decision,
        reason_codes=reason_codes,
        matched_policy_keys=matched_keys,
        required_role_slots=required_slots if decision == "require_approval" else (),
        approval_ttl_seconds=min(ttl_values) if decision == "require_approval" else None,
        matched=tuple(matched),
        provenance=provenance,
    )


def _ordered_unique(values: Any) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


@dataclass(frozen=True, slots=True)
class CommandFingerprintInput:
    org_id: str
    command_family: CommandFamily
    target_id: str
    definition_id: str
    command_type: str
    command_payload: Mapping[str, Any]
    expected_target_state: str | None
    expected_target_version: int | None

    def __post_init__(self) -> None:
        if any(
            not value
            for value in (
                self.org_id,
                self.target_id,
                self.definition_id,
                self.command_type,
            )
        ):
            raise ValueError("fingerprint identity fields must not be empty")
        if self.expected_target_version is not None and self.expected_target_version < 1:
            raise ValueError("expected target version must be positive")


def command_fingerprint(value: CommandFingerprintInput) -> str:
    """Hash the exact typed command intent using the kernel canonical JSON algorithm."""

    return canonical_checksum(
        {
            "org_id": value.org_id,
            "command_family": value.command_family,
            "target_id": value.target_id,
            "definition_id": value.definition_id,
            "command_type": value.command_type,
            "command_payload": dict(value.command_payload),
            "expected_target_state": value.expected_target_state,
            "expected_target_version": value.expected_target_version,
        }
    )


def _is_checksum(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


__all__ = [
    "ActorIdentity",
    "ActorKind",
    "AssignmentInheritanceMode",
    "AuthorityGrant",
    "CommandFamily",
    "CommandFingerprintInput",
    "MatchedPolicy",
    "PolicyDecision",
    "PolicyEvaluation",
    "PolicyProvenance",
    "RiskLevel",
    "RoleOccupancy",
    "ScopeAssignmentCandidate",
    "SlotInheritanceMode",
    "command_fingerprint",
    "evaluate_policies",
    "intersect_authority",
    "resolve_scope_assignments",
    "validate_separation_of_duties",
]
