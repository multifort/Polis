"""K1-T1 conformance tests for deterministic declarative protocol primitives."""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from polis.modules.kernel.domain.canonical import canonical_checksum, canonical_json_bytes
from polis.modules.kernel.domain.expressions import (
    ConditionFacts,
    evaluate_condition,
    evaluate_mapping,
    json_equal,
)
from polis.modules.kernel.domain.paths import MISSING, resolve_path
from polis.modules.kernel.errors import KernelProtocolError
from polis.modules.kernel.schema_profile import SchemaProfileV1
from polis.modules.kernel.schemas import (
    ConditionExprV1,
    MappingExprV1,
    validate_semver,
)


def test_rfc8785_canonical_vector_and_checksum_are_stable() -> None:
    value = {
        "numbers": [333333333.33333329, 1e30, 4.50, 2e-3, 1e-27],
        "string": '€$\x0f\nA\'B"\\"/',
        "literals": [None, True, False],
    }
    expected = (
        b'{"literals":[null,true,false],"numbers":[333333333.3333333,1e+30,4.5,0.002,'
        b'1e-27],"string":"\xe2\x82\xac$\\u000f\\nA\'B\\"\\\\\\"/"}'
    )
    assert canonical_json_bytes(value) == expected
    assert canonical_checksum(value) == canonical_checksum(json.loads(expected))


def test_checksum_is_stable_across_processes() -> None:
    value = {"z": [1, None], "a": {"b": "保持原 Unicode"}}
    script = (
        "import json; "
        "from polis.modules.kernel.domain.canonical import canonical_checksum; "
        f"print(canonical_checksum(json.loads({json.dumps(json.dumps(value))})))"
    )
    completed = subprocess.run(  # noqa: S603 - fixed interpreter and generated inert JSON literal
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
    )
    assert completed.stdout.strip() == canonical_checksum(value)


@pytest.mark.parametrize(
    "value,code",
    [
        (float("nan"), "JSON_NUMBER_NON_FINITE"),
        (-0.0, "JSON_NEGATIVE_ZERO"),
        (2**53, "JSON_INTEGER_OUT_OF_RANGE"),
    ],
)
def test_canonical_json_rejects_forbidden_numbers(value: object, code: str) -> None:
    with pytest.raises(KernelProtocolError, match=code):
        canonical_json_bytes(value)


def test_path_v1_preserves_missing_null_and_rfc6901_escapes() -> None:
    context = {"work": {"inputs": {"a/b": None, "t~n": 3}, "items": ["zero"]}}
    assert resolve_path(context, "/work/inputs/a~1b") is None
    assert resolve_path(context, "/work/inputs/t~0n") == 3
    assert resolve_path(context, "/work/items/0") == "zero"
    assert resolve_path(context, "/work/inputs/absent") is MISSING

    for invalid in ("$.work.inputs", "/unknown/value", "/work/~bad"):
        with pytest.raises(KernelProtocolError):
            resolve_path(context, invalid)


def test_conditions_use_strict_json_types_and_missing_semantics() -> None:
    context = {"work": {"inputs": {"value": 1, "nullable": None}}}
    assert not evaluate_condition(
        ConditionExprV1.model_validate({"op": "eq", "path": "/work/inputs/value", "value": True}),
        context,
        usage="guard",
    )
    assert evaluate_condition(
        ConditionExprV1.model_validate({"op": "exists", "path": "/work/inputs/nullable"}),
        context,
        usage="guard",
    )
    assert not evaluate_condition(
        ConditionExprV1.model_validate({"op": "eq", "path": "/work/inputs/absent", "value": None}),
        context,
        usage="guard",
    )
    assert evaluate_condition(
        ConditionExprV1.model_validate({"op": "not_exists", "path": "/work/inputs/absent"}),
        context,
        usage="guard",
    )
    assert json_equal({"a": 1, "b": [True]}, {"b": [True], "a": 1})


def test_ordered_condition_normalizes_timezone_and_rejects_type_mismatch() -> None:
    expression = ConditionExprV1.model_validate(
        {"op": "eq", "path": "/event/payload/outcome", "value": "pass"}
    )
    assert evaluate_condition(
        expression,
        {"event": {"payload": {"outcome": "pass"}}},
        usage="trigger",
    )

    later = ConditionExprV1.model_validate(
        {"op": "gt", "path": "/event/occurred_at", "value": "2026-07-21T09:59:59Z"}
    )
    assert evaluate_condition(
        later,
        {"event": {"occurred_at": "2026-07-21T18:00:00+08:00"}},
        usage="trigger",
    )

    fractional = ConditionExprV1.model_validate(
        {"op": "lt", "path": "/event/occurred_at", "value": "2026-07-21t10:00:00.5z"}
    )
    assert evaluate_condition(
        fractional,
        {"event": {"occurred_at": "2026-07-21T10:00:00Z"}},
        usage="trigger",
    )

    invalid = ConditionExprV1.model_validate(
        {"op": "lt", "path": "/work/inputs/value", "value": "2"}
    )
    with pytest.raises(KernelProtocolError, match="CONDITION_TYPE_MISMATCH"):
        evaluate_condition(invalid, {"work": {"inputs": {"value": 1}}}, usage="guard")


def test_condition_context_restrictions_and_unknown_fields() -> None:
    event_only = ConditionExprV1.model_validate(
        {"op": "event_field_matches", "path": "/event/type", "value": "work.completed"}
    )
    with pytest.raises(KernelProtocolError, match="CONDITION_OPERATOR_FORBIDDEN"):
        evaluate_condition(event_only, {"event": {"type": "work.completed"}}, usage="policy")

    with pytest.raises(ValidationError):
        ConditionExprV1.model_validate(
            {"op": "eq", "path": "/work/inputs/value", "value": 1, "expression": "run()"}
        )


def test_pathless_condition_operators_use_explicit_interpreter_facts() -> None:
    facts = ConditionFacts(
        filled_role_slots=frozenset({"owner"}),
        evaluation_outcome="pass",
    )
    role_filled = ConditionExprV1.model_validate(
        {"op": "role_slot_filled", "role_slot_key": "owner"}
    )
    outcome = ConditionExprV1.model_validate({"op": "evaluation_outcome_is", "value": "pass"})
    assert evaluate_condition(role_filled, {}, usage="guard", facts=facts)
    assert evaluate_condition(outcome, {}, usage="trigger", facts=facts)


def test_mapping_missing_rules_are_deterministic() -> None:
    object_mapping = MappingExprV1.model_validate(
        {
            "op": "object",
            "fields": {
                "kept": {"op": "from", "path": "/event/payload/id", "required": True},
                "omitted": {"op": "from", "path": "/event/payload/note", "required": False},
            },
        }
    )
    assert evaluate_mapping(object_mapping, {"event": {"payload": {"id": "r1"}}}) == {"kept": "r1"}

    array_mapping = MappingExprV1.model_validate(
        {
            "op": "array",
            "items": [{"op": "from", "path": "/event/payload/note", "required": False}],
        }
    )
    with pytest.raises(KernelProtocolError, match="MAPPING_ARRAY_ITEM_MISSING"):
        evaluate_mapping(array_mapping, {"event": {"payload": {}}})


def test_schema_profile_rejects_unknown_keywords_remote_refs_and_recursion() -> None:
    with pytest.raises(ValidationError) as unsupported:
        SchemaProfileV1.model_validate({"type": "string", "pattern": "^unsafe$"})
    assert unsupported.value.errors()[0]["type"] == "SCHEMA_KEYWORD_UNSUPPORTED"

    with pytest.raises(ValidationError) as remote:
        SchemaProfileV1.model_validate({"$ref": "https://example.com/schema.json"})
    assert remote.value.errors()[0]["type"] == "SCHEMA_REF_FORBIDDEN"

    with pytest.raises(ValidationError) as recursive:
        SchemaProfileV1.model_validate(
            {
                "$defs": {"node": {"$ref": "#/$defs/node"}},
                "$ref": "#/$defs/node",
            }
        )
    assert recursive.value.errors()[0]["type"] == "SCHEMA_REF_RECURSIVE"


def test_schema_profile_asserts_formats_and_explicit_object_policy() -> None:
    with pytest.raises(ValidationError) as missing_policy:
        SchemaProfileV1.model_validate({"type": "object", "properties": {}})
    assert missing_policy.value.errors()[0]["type"] == "SCHEMA_ADDITIONAL_PROPERTIES_REQUIRED"

    profile = SchemaProfileV1.model_validate(
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "required": ["requested_at"],
            "properties": {"requested_at": {"type": "string", "format": "date-time"}},
            "additionalProperties": False,
        }
    )
    profile.validate_instance({"requested_at": "2026-07-21T10:00:00Z"})
    with pytest.raises(KernelProtocolError, match="SCHEMA_INSTANCE_INVALID"):
        profile.validate_instance({"requested_at": "2026-07-21 10:00:00"})


@pytest.mark.parametrize("version", ["0.0.0", "1.2.3", "10.20.30"])
def test_semver_accepts_exact_three_component_versions(version: str) -> None:
    assert validate_semver(version) == version


@pytest.mark.parametrize("version", ["1", "1.2", "01.2.3", "1.2.3-alpha", "v1.2.3"])
def test_semver_rejects_non_contract_versions(version: str) -> None:
    with pytest.raises(KernelProtocolError, match="SEMVER_INVALID"):
        validate_semver(version)


def test_kernel_domain_has_no_service_framework_dependencies() -> None:
    domain_root = Path(__file__).resolve().parents[2] / "src/polis/modules/kernel/domain"
    forbidden_roots = {"fastapi", "sqlalchemy", "temporalio", "litellm", "mcp"}
    for path in domain_root.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imports = {
            name.name.split(".", 1)[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for name in node.names
        }
        imports.update(
            node.module.split(".", 1)[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module is not None
        )
        assert imports.isdisjoint(forbidden_roots), (
            f"{path.name} imports {imports & forbidden_roots}"
        )
