"""Deterministic evaluators for ConditionExprV1 and MappingExprV1."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from polis.modules.kernel.domain.paths import MISSING, resolve_path
from polis.modules.kernel.errors import KernelProtocolError
from polis.modules.kernel.schemas import (
    ArrayMapping,
    CoalesceMapping,
    CompareExpr,
    ConditionExprV1,
    ConditionNode,
    ConstMapping,
    EvalExpr,
    EventExpr,
    ExistsExpr,
    FromMapping,
    LogicalExpr,
    MappingExprV1,
    MappingNode,
    NotExpr,
    ObjectMapping,
    SetExpr,
    SlotExpr,
)

ConditionContext = Literal["guard", "policy", "trigger"]
EvaluationOutcome = Literal["pass", "rework", "human_review", "fail"]
_RFC3339 = re.compile(r"^\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[Zz]|[+-]\d{2}:\d{2})$")


@dataclass(frozen=True, slots=True)
class ConditionFacts:
    """Facts for condition operators that intentionally have no PathV1 operand."""

    filled_role_slots: frozenset[str] = field(default_factory=frozenset)
    evaluation_outcome: EvaluationOutcome | None = None


def _parse_datetime(value: str) -> datetime:
    if _RFC3339.fullmatch(value) is None:
        raise KernelProtocolError(
            "DATETIME_INVALID", "", "date-time must be RFC 3339 with an explicit timezone"
        )
    try:
        normalized = value.replace("t", "T").replace("z", "Z").replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise KernelProtocolError("DATETIME_INVALID", "", "invalid RFC 3339 date-time") from exc
    if parsed.tzinfo is None:
        raise KernelProtocolError("DATETIME_TIMEZONE_REQUIRED", "", "date-time needs a timezone")
    return parsed.astimezone(UTC)


def normalize_datetime(value: str) -> str:
    """Validate an RFC 3339 timestamp and normalize it to UTC Z."""

    normalized = _parse_datetime(value).isoformat().replace("+00:00", "Z")
    return normalized.replace(".000000Z", "Z")


def _json_kind(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, Mapping):
        return "object"
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return "array"
    return "unsupported"


def json_equal(left: Any, right: Any) -> bool:
    """Compare JSON values without Python's bool/int coercion."""

    if _json_kind(left) != _json_kind(right):
        return False
    if isinstance(left, Mapping) and isinstance(right, Mapping):
        return set(left) == set(right) and all(json_equal(left[key], right[key]) for key in left)
    if (
        isinstance(left, Sequence)
        and not isinstance(left, (str, bytes, bytearray))
        and isinstance(right, Sequence)
        and not isinstance(right, (str, bytes, bytearray))
    ):
        return len(left) == len(right) and all(
            json_equal(left_item, right_item)
            for left_item, right_item in zip(left, right, strict=True)
        )
    return bool(left == right)


def _ordered_comparison(left: Any, right: Any, *, path: str) -> int:
    if (
        isinstance(left, (int, float))
        and not isinstance(left, bool)
        and isinstance(right, (int, float))
        and not isinstance(right, bool)
    ):
        return (left > right) - (left < right)
    if isinstance(left, str) and isinstance(right, str):
        try:
            parsed_left = _parse_datetime(left)
            parsed_right = _parse_datetime(right)
            return (parsed_left > parsed_right) - (parsed_left < parsed_right)
        except KernelProtocolError as exc:
            raise KernelProtocolError(
                "CONDITION_TYPE_MISMATCH",
                path,
                "ordered comparison requires numbers or RFC 3339 date-times",
            ) from exc
    raise KernelProtocolError(
        "CONDITION_TYPE_MISMATCH",
        path,
        "ordered comparison requires matching number or date-time operands",
    )


def evaluate_condition(
    expression: ConditionExprV1 | ConditionNode,
    context: Mapping[str, Any],
    *,
    usage: ConditionContext,
    facts: ConditionFacts | None = None,
) -> bool:
    """Evaluate one validated condition against an immutable context snapshot."""

    node = expression.root if isinstance(expression, ConditionExprV1) else expression
    resolved_facts = facts or ConditionFacts()
    if isinstance(node, EventExpr):
        if usage != "trigger":
            raise KernelProtocolError(
                "CONDITION_OPERATOR_FORBIDDEN", "", "event_field_matches is trigger-only"
            )
        actual = resolve_path(context, node.path.root)
        return actual is not MISSING and json_equal(actual, node.value)
    if isinstance(node, EvalExpr):
        if usage not in {"guard", "trigger"}:
            raise KernelProtocolError(
                "CONDITION_OPERATOR_FORBIDDEN",
                "",
                "evaluation_outcome_is is only valid for guards and triggers",
            )
        return resolved_facts.evaluation_outcome == node.value
    if isinstance(node, SlotExpr):
        return node.role_slot_key in resolved_facts.filled_role_slots
    if isinstance(node, ExistsExpr):
        actual = resolve_path(context, node.path.root)
        if node.op in {"exists", "input_exists", "artifact_exists"}:
            return actual is not MISSING
        return actual is MISSING
    if isinstance(node, LogicalExpr):
        if node.op == "all":
            return all(
                evaluate_condition(child, context, usage=usage, facts=resolved_facts)
                for child in node.conditions
            )
        return any(
            evaluate_condition(child, context, usage=usage, facts=resolved_facts)
            for child in node.conditions
        )
    if isinstance(node, NotExpr):
        return not evaluate_condition(
            node.condition,
            context,
            usage=usage,
            facts=resolved_facts,
        )
    if isinstance(node, SetExpr):
        actual = resolve_path(context, node.path.root)
        if actual is MISSING:
            return False
        contained = any(json_equal(actual, candidate) for candidate in node.value)
        return contained if node.op == "in" else not contained
    if isinstance(node, CompareExpr):
        actual = resolve_path(context, node.path.root)
        if actual is MISSING:
            return False
        if node.op == "eq":
            return json_equal(actual, node.value)
        if node.op == "ne":
            return not json_equal(actual, node.value)
        comparison = _ordered_comparison(actual, node.value, path=node.path.root)
        if node.op == "lt":
            return comparison < 0
        if node.op == "lte":
            return comparison <= 0
        if node.op == "gt":
            return comparison > 0
        return comparison >= 0
    raise AssertionError(f"unsupported condition node: {type(node).__name__}")


def evaluate_mapping(expression: MappingExprV1 | MappingNode, context: Mapping[str, Any]) -> Any:
    """Evaluate one validated mapping without mutating its source context."""

    node = expression.root if isinstance(expression, MappingExprV1) else expression
    if isinstance(node, ConstMapping):
        return node.value
    if isinstance(node, FromMapping):
        value = resolve_path(context, node.path.root)
        if value is MISSING and node.required:
            raise KernelProtocolError(
                "MAPPING_SOURCE_MISSING", node.path.root, "required mapping source is missing"
            )
        return value
    if isinstance(node, CoalesceMapping):
        for candidate in node.values:
            value = evaluate_mapping(candidate, context)
            if value is not MISSING and value is not None:
                return value
        return MISSING
    if isinstance(node, ObjectMapping):
        object_result: dict[str, Any] = {}
        for field, child in node.fields.items():
            value = evaluate_mapping(child, context)
            if value is not MISSING:
                object_result[field] = value
        return object_result
    if isinstance(node, ArrayMapping):
        array_result: list[Any] = []
        for index, child in enumerate(node.items):
            value = evaluate_mapping(child, context)
            if value is MISSING:
                raise KernelProtocolError(
                    "MAPPING_ARRAY_ITEM_MISSING",
                    f"/items/{index}",
                    "optional missing values cannot be omitted from arrays",
                )
            array_result.append(value)
        return array_result
    raise AssertionError(f"unsupported mapping node: {type(node).__name__}")


__all__ = [
    "ConditionContext",
    "ConditionFacts",
    "evaluate_condition",
    "evaluate_mapping",
    "json_equal",
    "normalize_datetime",
]
