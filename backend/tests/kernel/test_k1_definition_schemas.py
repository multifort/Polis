"""K1-T1 conformance tests for complete Definition V1 contracts."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, cast

import pytest
import yaml  # type: ignore[import-untyped]
from pydantic import TypeAdapter, ValidationError

from polis.modules.kernel.schemas import (
    DEFINITION_V1_ADAPTER,
    MAX_CONDITION_BYTES,
    MAX_CONDITION_DEPTH,
    MAX_CONDITION_NODES,
    MAX_MAPPING_BYTES,
    MAX_MAPPING_DEPTH,
    MAX_MAPPING_NODES,
    ActorKind,
    ApprovalPurpose,
    AssignmentMode,
    Cardinality,
    ConditionExprV1,
    DomainPackageDefinitionV1,
    EvaluationOutcome,
    ExecutionPolicy,
    HumanReviewRejectAction,
    InheritanceMode,
    MappingExprV1,
    MisfirePolicy,
    PolicyDecision,
    ResponsibilityKind,
    RetryableFailureClass,
    RiskLevel,
    RoleDefinitionV1,
    StateCategory,
    Visibility,
    WorkDefinitionV1,
    definition_checksum,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
FIXTURE_PATH = REPOSITORY_ROOT / "docs/design/v3/kernel/fixtures/generic-definition-set-v1.json"
MANIFEST_PATH = REPOSITORY_ROOT / "docs/design/v3/kernel/protocol-manifest.yaml"


@pytest.fixture(scope="module")
def definition_set() -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(FIXTURE_PATH.read_text(encoding="utf-8")))


def _definitions(definition_set: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        definition_set["domain_package"],
        *definition_set["roles"],
        *definition_set["works"],
    ]


def _work(definition_set: dict[str, Any], index: int = 1) -> dict[str, Any]:
    return copy.deepcopy(definition_set["works"][index])


def _error_types(exc: ValidationError) -> set[str]:
    return {str(error["type"]) for error in exc.errors()}


def test_complete_fixture_round_trips_and_checksums_are_stable(
    definition_set: dict[str, Any],
) -> None:
    parsed = [DEFINITION_V1_ADAPTER.validate_python(item) for item in _definitions(definition_set)]
    assert [type(item) for item in parsed] == [
        DomainPackageDefinitionV1,
        RoleDefinitionV1,
        RoleDefinitionV1,
        WorkDefinitionV1,
        WorkDefinitionV1,
    ]
    for source, definition in zip(_definitions(definition_set), parsed, strict=True):
        dumped = definition.model_dump(mode="json", by_alias=True)
        assert dumped == source
        reparsed = DEFINITION_V1_ADAPTER.validate_python(dumped)
        assert definition_checksum(reparsed) == definition_checksum(definition)
        assert dumped["definition_kind"] == definition.definition_kind


@pytest.mark.parametrize("kind", [None, "unknown", "role"])
def test_definition_discriminator_must_match_payload(
    definition_set: dict[str, Any], kind: str | None
) -> None:
    value = copy.deepcopy(definition_set["domain_package"])
    if kind is None:
        value.pop("definition_kind")
    else:
        value["definition_kind"] = kind
    with pytest.raises(ValidationError) as invalid:
        DEFINITION_V1_ADAPTER.validate_python(value)
    assert "DEFINITION_KIND_MISMATCH" in _error_types(invalid.value) or kind == "role"


def test_definition_rejects_missing_extra_and_unknown_effect(
    definition_set: dict[str, Any],
) -> None:
    missing = _work(definition_set)
    missing.pop("planning_profile")
    with pytest.raises(ValidationError, match="planning_profile"):
        DEFINITION_V1_ADAPTER.validate_python(missing)

    extra = _work(definition_set)
    extra["agent_prompt"] = "do everything"
    with pytest.raises(ValidationError, match="extra_forbidden"):
        DEFINITION_V1_ADAPTER.validate_python(extra)

    unknown_effect = _work(definition_set)
    unknown_effect["state_machine"]["transitions"][0]["effects"] = [{"type": "shell"}]
    with pytest.raises(ValidationError) as invalid:
        DEFINITION_V1_ADAPTER.validate_python(unknown_effect)
    assert "EFFECT_TYPE_UNSUPPORTED" in _error_types(invalid.value)


@pytest.mark.parametrize(
    "mutate,error_type",
    [
        (
            lambda work: work["planning_profile"].update({"max_nodes": 2, "max_parallel_nodes": 3}),
            "PLANNING_PROFILE_INVALID",
        ),
        (
            lambda work: work["execution_profile"].update(
                {"max_parallel_nodes": work["planning_profile"]["max_parallel_nodes"] + 1}
            ),
            "EXECUTION_PROFILE_INVALID",
        ),
        (
            lambda work: work["execution_profile"].update(
                {"heartbeat_timeout_seconds": work["execution_profile"]["node_timeout_seconds"] + 1}
            ),
            "EXECUTION_PROFILE_INVALID",
        ),
    ],
)
def test_planning_and_execution_cross_limits(
    definition_set: dict[str, Any], mutate: Any, error_type: str
) -> None:
    work = _work(definition_set)
    mutate(work)
    with pytest.raises(ValidationError) as invalid:
        DEFINITION_V1_ADAPTER.validate_python(work)
    assert error_type in _error_types(invalid.value)


def test_role_slot_state_policy_and_effect_references_are_closed(
    definition_set: dict[str, Any],
) -> None:
    slot = _work(definition_set)
    slot["role_slots"][0]["separation_of_duties_from"] = ["missing"]
    with pytest.raises(ValidationError) as invalid_slot:
        DEFINITION_V1_ADAPTER.validate_python(slot)
    assert "DEFINITION_REFERENCE_UNKNOWN" in _error_types(invalid_slot.value)

    state = _work(definition_set)
    state["state_machine"]["transitions"][0]["to"] = "missing"
    with pytest.raises(ValidationError) as invalid_state:
        DEFINITION_V1_ADAPTER.validate_python(state)
    assert "DEFINITION_REFERENCE_UNKNOWN" in _error_types(invalid_state.value)

    policy = _work(definition_set)
    policy["policy_bindings"][0]["approval_ttl_seconds"] = None
    with pytest.raises(ValidationError) as invalid_policy:
        DEFINITION_V1_ADAPTER.validate_python(policy)
    assert "EFFECT_PAYLOAD_INVALID" in _error_types(invalid_policy.value)

    evaluation_effect = _work(definition_set)
    evaluation_effect["state_machine"]["transitions"][0]["effects"] = [
        {"type": "request_evaluation", "evaluation_rule_keys": ["missing"]}
    ]
    with pytest.raises(ValidationError) as invalid_effect:
        DEFINITION_V1_ADAPTER.validate_python(evaluation_effect)
    assert "DEFINITION_REFERENCE_UNKNOWN" in _error_types(invalid_effect.value)


def test_policy_and_evaluation_reject_runtime_only_condition_operators(
    definition_set: dict[str, Any],
) -> None:
    policy = _work(definition_set)
    policy["policy_bindings"][0]["when"] = [
        {"op": "event_field_matches", "path": "/event/type", "value": "work.completed"}
    ]
    with pytest.raises(ValidationError) as invalid_policy:
        DEFINITION_V1_ADAPTER.validate_python(policy)
    assert "CONDITION_OPERATOR_FORBIDDEN" in _error_types(invalid_policy.value)

    evaluation = _work(definition_set)
    evaluation["evaluation_rules"][0]["when"] = [{"op": "evaluation_outcome_is", "value": "pass"}]
    with pytest.raises(ValidationError) as invalid_evaluation:
        DEFINITION_V1_ADAPTER.validate_python(evaluation)
    assert "CONDITION_OPERATOR_FORBIDDEN" in _error_types(invalid_evaluation.value)


def test_trigger_child_dependency_contract_is_exact(definition_set: dict[str, Any]) -> None:
    missing = _work(definition_set)
    child_trigger = missing["triggers"][-1]
    child_trigger["emit_command"]["child_bundle_dependency_key"] = None
    with pytest.raises(ValidationError) as invalid_missing:
        DEFINITION_V1_ADAPTER.validate_python(missing)
    assert "TRIGGER_COMMAND_INVALID" in _error_types(invalid_missing.value)

    unexpected = _work(definition_set)
    unexpected["triggers"][0]["emit_command"]["child_bundle_dependency_key"] = "remediation_v1"
    with pytest.raises(ValidationError) as invalid_unexpected:
        DEFINITION_V1_ADAPTER.validate_python(unexpected)
    assert "TRIGGER_COMMAND_INVALID" in _error_types(invalid_unexpected.value)

    unknown = _work(definition_set)
    unknown["triggers"][-1]["emit_command"]["child_bundle_dependency_key"] = "missing"
    with pytest.raises(ValidationError) as invalid_unknown:
        DEFINITION_V1_ADAPTER.validate_python(unknown)
    assert "DEFINITION_REFERENCE_UNKNOWN" in _error_types(invalid_unknown.value)


@pytest.mark.parametrize(
    "effect",
    [
        {"type": "request_plan"},
        {"type": "start_run"},
        {"type": "cancel_run", "reason_code": "USER_CANCELLED"},
        {"type": "request_evaluation", "evaluation_rule_keys": ["outcome_pass"]},
        {
            "type": "request_approval",
            "approval_purpose": "quality_review",
            "required_role_slots": ["owner"],
            "ttl_seconds": 3600,
        },
        {
            "type": "emit_event",
            "event_type": "work.accepted",
            "payload_mapping": {"op": "object", "fields": {}},
        },
        {
            "type": "create_child_work",
            "dependency_key": "remediation_v1",
            "input_mapping": {"op": "object", "fields": {}},
        },
        {
            "type": "schedule_command",
            "command_type": "resume_work",
            "delay_seconds": 60,
            "timezone": "Asia/Shanghai",
            "misfire_policy": "fire_once",
            "payload_mapping": {"op": "object", "fields": {}},
        },
    ],
)
def test_all_effect_payload_variants_are_explicit(
    definition_set: dict[str, Any], effect: dict[str, Any]
) -> None:
    work = _work(definition_set)
    work["state_machine"]["transitions"][0]["effects"] = [effect]
    DEFINITION_V1_ADAPTER.validate_python(work)


def test_mapping_resource_limits_are_enforced() -> None:
    deep: dict[str, Any] = {"op": "const", "value": 1}
    for _ in range(17):
        deep = {"op": "array", "items": [deep]}
    with pytest.raises(ValidationError) as depth:
        MappingExprV1.model_validate(deep)
    assert "MAPPING_DEPTH_EXCEEDED" in _error_types(depth.value)

    wide = {"op": "array", "items": [{"op": "const", "value": index} for index in range(256)]}
    with pytest.raises(ValidationError) as nodes:
        MappingExprV1.model_validate(wide)
    assert "MAPPING_NODE_LIMIT_EXCEEDED" in _error_types(nodes.value)

    large = {"op": "const", "value": "x" * MAX_MAPPING_BYTES}
    with pytest.raises(ValidationError) as size:
        MappingExprV1.model_validate(large)
    assert "MAPPING_SIZE_EXCEEDED" in _error_types(size.value)


def test_condition_resource_limits_are_enforced() -> None:
    deep: dict[str, Any] = {"op": "exists", "path": "/work/inputs/value"}
    for _ in range(17):
        deep = {"op": "not", "condition": deep}
    with pytest.raises(ValidationError) as depth:
        ConditionExprV1.model_validate(deep)
    assert "CONDITION_DEPTH_EXCEEDED" in _error_types(depth.value)

    wide = {
        "op": "all",
        "conditions": [{"op": "exists", "path": "/work/inputs/value"} for _ in range(256)],
    }
    with pytest.raises(ValidationError) as nodes:
        ConditionExprV1.model_validate(wide)
    assert "CONDITION_NODE_LIMIT_EXCEEDED" in _error_types(nodes.value)

    large = {
        "op": "eq",
        "path": "/work/inputs/value",
        "value": "x" * MAX_CONDITION_BYTES,
    }
    with pytest.raises(ValidationError) as size:
        ConditionExprV1.model_validate(large)
    assert "CONDITION_SIZE_EXCEEDED" in _error_types(size.value)


def test_manifest_definition_contract_matches_code_constants() -> None:
    manifest = yaml.safe_load(MANIFEST_PATH.read_text(encoding="utf-8"))
    contract = manifest["definition_schema_v1"]
    assert contract["kinds"] == ["domain_package", "role", "work"]
    assert contract["effect_types"] == [
        "request_plan",
        "start_run",
        "cancel_run",
        "request_evaluation",
        "request_approval",
        "emit_event",
        "create_child_work",
        "schedule_command",
    ]
    enum_types = {
        "visibility": Visibility,
        "risk_level": RiskLevel,
        "actor_kind": ActorKind,
        "policy_decision": PolicyDecision,
        "cardinality": Cardinality,
        "responsibility_kind": ResponsibilityKind,
        "execution_policy": ExecutionPolicy,
        "inheritance_mode": InheritanceMode,
        "state_category": StateCategory,
        "evaluation_outcome": EvaluationOutcome,
        "assignment_mode": AssignmentMode,
        "human_review_reject_action": HumanReviewRejectAction,
        "misfire_policy": MisfirePolicy,
        "approval_purpose": ApprovalPurpose,
        "retryable_failure_class": RetryableFailureClass,
    }
    assert set(contract["enums"]) == set(enum_types)
    for name, enum_type in enum_types.items():
        assert contract["enums"][name] == TypeAdapter(enum_type).json_schema()["enum"]

    assert contract["limits"]["condition_depth"] == MAX_CONDITION_DEPTH
    assert contract["limits"]["condition_nodes"] == MAX_CONDITION_NODES
    assert contract["limits"]["condition_bytes"] == MAX_CONDITION_BYTES
    assert contract["limits"]["mapping_depth"] == MAX_MAPPING_DEPTH
    assert contract["limits"]["mapping_nodes"] == MAX_MAPPING_NODES
    assert contract["limits"]["mapping_bytes"] == MAX_MAPPING_BYTES
