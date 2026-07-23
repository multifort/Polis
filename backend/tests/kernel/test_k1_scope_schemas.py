"""K1-T4 contracts for governance policy and assignment restrictions."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from polis.modules.kernel.domain.governance import (
    DEFINITION_COMMANDS,
    GOVERNANCE_COMMANDS,
    GOVERNANCE_DOMAIN_CHECKSUM,
    GOVERNANCE_DOMAIN_DEFINITION,
    GOVERNANCE_OWNER_ROLE_CHECKSUM,
    GOVERNANCE_OWNER_ROLE_DEFINITION,
    SCOPE_COMMANDS,
)
from polis.modules.kernel.errors import KernelProtocolError
from polis.modules.kernel.schemas import (
    AuthorityConstraintsV1,
    OrgPolicyV1,
    RoleAuthorityV1,
)


def _authority() -> RoleAuthorityV1:
    return RoleAuthorityV1(
        commands=["create_scope", "update_scope"],
        tools=["artifact.read"],
        data_scopes=["kernel.scopes"],
        max_risk_level="high",
        budget_cents=100_000,
    )


def test_authority_constraints_are_canonical_restrictions() -> None:
    constraints = AuthorityConstraintsV1(
        commands=["update_scope", "create_scope"],
        tools=[],
        max_risk_level="medium",
        budget_cents=10_000,
    )
    constraints.validate_subset_of(_authority())

    assert constraints.canonical_value() == {
        "commands": ["create_scope", "update_scope"],
        "tools": [],
        "max_risk_level": "medium",
        "budget_cents": 10_000,
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("commands", ["archive_scope"]),
        ("tools", ["artifact.delete"]),
        ("data_scopes", ["kernel.secrets"]),
        ("max_risk_level", "critical"),
        ("budget_cents", 100_001),
    ],
)
def test_authority_constraints_reject_escalation(field: str, value: object) -> None:
    constraints = AuthorityConstraintsV1.model_validate({field: value})

    with pytest.raises(KernelProtocolError, match="ASSIGNMENT_AUTHORITY_ESCALATION"):
        constraints.validate_subset_of(_authority())


def test_authority_constraints_reject_unknown_or_duplicate_values() -> None:
    with pytest.raises(ValidationError):
        AuthorityConstraintsV1.model_validate({"unknown": True})
    with pytest.raises(ValidationError):
        AuthorityConstraintsV1(commands=["create_scope", "create_scope"])


def test_org_policy_is_strict_bounded_and_checksum_is_stable() -> None:
    raw = {
        "kernel_policy": {
            "schema_version": 1,
            "max_concurrent_runs": 20,
            "budget_limit_cents": 0,
            "budget_enforcement": "observe",
            "default_approval_ttl_seconds": 86_400,
        }
    }
    left = OrgPolicyV1.model_validate(raw)
    right = OrgPolicyV1.model_validate(raw)
    assert left.checksum == right.checksum
    assert len(left.checksum) == 64

    with pytest.raises(ValidationError):
        OrgPolicyV1.model_validate(
            {
                **raw,
                "extra": True,
            }
        )


def test_governance_seeds_are_published_contract_material() -> None:
    assert GOVERNANCE_DOMAIN_DEFINITION.key == "kernel.governance"
    assert GOVERNANCE_OWNER_ROLE_DEFINITION.key == "kernel.governance_owner"
    assert tuple(GOVERNANCE_OWNER_ROLE_DEFINITION.authority.commands) == GOVERNANCE_COMMANDS
    assert GOVERNANCE_COMMANDS == DEFINITION_COMMANDS + SCOPE_COMMANDS
    assert len(GOVERNANCE_DOMAIN_CHECKSUM) == 64
    assert len(GOVERNANCE_OWNER_ROLE_CHECKSUM) == 64
