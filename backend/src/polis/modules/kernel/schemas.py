"""Pydantic contracts for the V3 declarative kernel protocol."""

from __future__ import annotations

import re
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    RootModel,
    StringConstraints,
    field_validator,
    model_validator,
)
from pydantic_core import PydanticCustomError

from polis.modules.kernel.domain.paths import parse_path
from polis.modules.kernel.errors import KernelProtocolError
from polis.modules.kernel.schema_profile import SchemaProfileV1

MAX_CONDITION_DEPTH = 16
MAX_CONDITION_NODES = 256

KeyV1 = Annotated[
    str,
    StringConstraints(
        min_length=1,
        pattern=r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*$",
    ),
]
LocalKeyV1 = Annotated[
    str,
    StringConstraints(min_length=1, pattern=r"^[a-z][a-z0-9_]*$"),
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, validate_default=True)


class PathV1(RootModel[str]):
    """RFC 6901 JSON Pointer restricted to kernel context roots."""

    @field_validator("root")
    @classmethod
    def validate_path(cls, value: str) -> str:
        try:
            parse_path(value)
        except KernelProtocolError as exc:
            raise PydanticCustomError(exc.code, exc.issue.message, {"path": exc.path}) from exc
        return value


class CompareExpr(StrictModel):
    op: Literal["eq", "ne", "lt", "lte", "gt", "gte"]
    path: PathV1
    value: JsonValue


class SetExpr(StrictModel):
    op: Literal["in", "not_in"]
    path: PathV1
    value: list[JsonValue]


class ExistsExpr(StrictModel):
    op: Literal["exists", "not_exists", "input_exists", "artifact_exists"]
    path: PathV1


class LogicalExpr(StrictModel):
    op: Literal["all", "any"]
    conditions: list[ConditionNode]


class NotExpr(StrictModel):
    op: Literal["not"]
    condition: ConditionNode


class SlotExpr(StrictModel):
    op: Literal["role_slot_filled"]
    role_slot_key: LocalKeyV1


class EvalExpr(StrictModel):
    op: Literal["evaluation_outcome_is"]
    value: Literal["pass", "rework", "human_review", "fail"]


class EventExpr(StrictModel):
    op: Literal["event_field_matches"]
    path: PathV1
    value: JsonValue


ConditionNode = Annotated[
    CompareExpr | SetExpr | ExistsExpr | LogicalExpr | NotExpr | SlotExpr | EvalExpr | EventExpr,
    Field(discriminator="op"),
]


def _condition_size(node: ConditionNode) -> tuple[int, int]:
    if isinstance(node, LogicalExpr):
        children = [_condition_size(child) for child in node.conditions]
        return 1 + sum(count for count, _ in children), 1 + max(
            (depth for _, depth in children), default=0
        )
    if isinstance(node, NotExpr):
        count, depth = _condition_size(node.condition)
        return count + 1, depth + 1
    return 1, 1


class ConditionExprV1(RootModel[ConditionNode]):
    @model_validator(mode="after")
    def validate_limits(self) -> ConditionExprV1:
        count, depth = _condition_size(self.root)
        if count > MAX_CONDITION_NODES:
            raise PydanticCustomError(
                "CONDITION_NODE_LIMIT_EXCEEDED",
                f"condition AST exceeds {MAX_CONDITION_NODES} nodes",
            )
        if depth > MAX_CONDITION_DEPTH:
            raise PydanticCustomError(
                "CONDITION_DEPTH_EXCEEDED",
                f"condition AST exceeds depth {MAX_CONDITION_DEPTH}",
            )
        return self


class ConstMapping(StrictModel):
    op: Literal["const"]
    value: JsonValue


class FromMapping(StrictModel):
    op: Literal["from"]
    path: PathV1
    required: bool


class CoalesceMapping(StrictModel):
    op: Literal["coalesce"]
    values: list[MappingNode]

    @field_validator("values")
    @classmethod
    def require_values(cls, value: list[MappingNode]) -> list[MappingNode]:
        if not value:
            raise ValueError("coalesce requires at least one value")
        return value


class ObjectMapping(StrictModel):
    op: Literal["object"]
    fields: dict[str, MappingNode]


class ArrayMapping(StrictModel):
    op: Literal["array"]
    items: list[MappingNode]


MappingNode = Annotated[
    ConstMapping | FromMapping | CoalesceMapping | ObjectMapping | ArrayMapping,
    Field(discriminator="op"),
]


class MappingExprV1(RootModel[MappingNode]):
    pass


def validate_semver(value: str) -> str:
    """Validate the V3 exact MAJOR.MINOR.PATCH version form."""

    if re.fullmatch(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)", value) is None:
        raise KernelProtocolError("SEMVER_INVALID", "", "version must be MAJOR.MINOR.PATCH")
    return value


LogicalExpr.model_rebuild()
NotExpr.model_rebuild()
CoalesceMapping.model_rebuild()
ObjectMapping.model_rebuild()
ArrayMapping.model_rebuild()

__all__ = [
    "ConditionExprV1",
    "ConditionNode",
    "KeyV1",
    "LocalKeyV1",
    "MappingExprV1",
    "MappingNode",
    "PathV1",
    "SchemaProfileV1",
    "validate_semver",
]
