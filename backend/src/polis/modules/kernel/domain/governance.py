"""Immutable K1 governance seed and policy contracts."""

from __future__ import annotations

from typing import Final

from polis.modules.kernel.schemas import (
    DomainPackageDefinitionV1,
    RoleDefinitionV1,
    definition_checksum,
)

GOVERNANCE_DOMAIN_KEY: Final = "kernel.governance"
GOVERNANCE_OWNER_ROLE_KEY: Final = "kernel.governance_owner"
GOVERNANCE_SEED_VERSION: Final = "1.0.0"
GOVERNANCE_SCOPE_TYPE: Final = "org_governance"

DEFINITION_COMMANDS: Final[tuple[str, ...]] = (
    "create_domain_package_definition",
    "update_domain_package_definition_draft",
    "publish_domain_package_definition",
    "deprecate_domain_package_definition",
    "create_work_definition",
    "update_work_definition_draft",
    "publish_work_definition",
    "deprecate_work_definition",
    "create_role_definition",
    "update_role_definition_draft",
    "publish_role_definition",
    "deprecate_role_definition",
    "compile_definition_bundle",
    "decide_definition_approval",
    "expire_definition_approval",
    "revoke_definition_approval",
)
SCOPE_COMMANDS: Final[tuple[str, ...]] = (
    "create_scope",
    "update_scope",
    "archive_scope",
    "relate_scopes",
    "unrelate_scopes",
    "assign_scope_role",
    "activate_scope_role",
    "suspend_scope_role",
    "end_scope_role",
    "cancel_scope_schedule",
    "decide_scope_approval",
    "expire_scope_approval",
    "revoke_scope_approval",
)
GOVERNANCE_COMMANDS: Final[tuple[str, ...]] = DEFINITION_COMMANDS + SCOPE_COMMANDS

GOVERNANCE_DOMAIN_DEFINITION: Final = DomainPackageDefinitionV1.model_validate(
    {
        "schema_version": 1,
        "definition_kind": "domain_package",
        "key": GOVERNANCE_DOMAIN_KEY,
        "display_name": "Polis Organization Governance",
        "scope_types": [
            {
                "key": GOVERNANCE_SCOPE_TYPE,
                "parent_types": [],
                "attributes_schema": {
                    "type": "object",
                    "required": ["kernel_policy"],
                    "properties": {
                        "kernel_policy": {
                            "type": "object",
                            "required": ["schema_version"],
                            "properties": {
                                "schema_version": {
                                    "type": "integer",
                                    "const": 1,
                                }
                            },
                            "additionalProperties": True,
                        }
                    },
                    "additionalProperties": False,
                },
            }
        ],
        "relationship_types": [],
        "policy_defaults": {
            "unknown_action": "deny",
            "dangerous_action": "require_approval",
        },
        "compatible_work_definition_keys": [],
        "compatible_role_definition_keys": [GOVERNANCE_OWNER_ROLE_KEY],
    }
)

GOVERNANCE_OWNER_ROLE_DEFINITION: Final = RoleDefinitionV1.model_validate(
    {
        "schema_version": 1,
        "definition_kind": "role",
        "key": GOVERNANCE_OWNER_ROLE_KEY,
        "display_name": "Organization Governance Owner",
        "mission": "Own the organization's Polis kernel governance configuration",
        "accountabilities": [
            "Maintain governance definitions and policy",
            "Authorize scope administration",
        ],
        "required_capabilities": [],
        "authority": {
            "commands": list(GOVERNANCE_COMMANDS),
            "tools": [],
            "data_scopes": [
                "kernel.definitions",
                "kernel.scopes",
                "kernel.governance",
            ],
            "max_risk_level": "critical",
            "budget_cents": 1_000_000_000_000_000,
        },
        "collaboration": {
            "receives_from": [],
            "hands_off_to": [],
            "escalates_to": [],
        },
        "quality_bar": {"evaluation_rule_keys": []},
        "capacity": {"max_active_work_items": 10_000},
    }
)

GOVERNANCE_DOMAIN_CHECKSUM: Final = definition_checksum(GOVERNANCE_DOMAIN_DEFINITION)
GOVERNANCE_OWNER_ROLE_CHECKSUM: Final = definition_checksum(GOVERNANCE_OWNER_ROLE_DEFINITION)


__all__ = [
    "DEFINITION_COMMANDS",
    "GOVERNANCE_COMMANDS",
    "GOVERNANCE_DOMAIN_CHECKSUM",
    "GOVERNANCE_DOMAIN_DEFINITION",
    "GOVERNANCE_DOMAIN_KEY",
    "GOVERNANCE_OWNER_ROLE_CHECKSUM",
    "GOVERNANCE_OWNER_ROLE_DEFINITION",
    "GOVERNANCE_OWNER_ROLE_KEY",
    "GOVERNANCE_SCOPE_TYPE",
    "GOVERNANCE_SEED_VERSION",
    "SCOPE_COMMANDS",
]
