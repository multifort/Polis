"""Pydantic contracts for the V3 declarative kernel protocol."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Discriminator,
    Field,
    JsonValue,
    RootModel,
    StringConstraints,
    TypeAdapter,
    field_validator,
    model_validator,
)
from pydantic_core import PydanticCustomError

from polis.modules.kernel.domain.canonical import canonical_json_bytes
from polis.modules.kernel.domain.paths import parse_path
from polis.modules.kernel.errors import KernelProtocolError
from polis.modules.kernel.schema_profile import SchemaProfileV1

MAX_CONDITION_DEPTH = 16
MAX_CONDITION_NODES = 256
MAX_CONDITION_BYTES = 64 * 1024
MAX_MAPPING_DEPTH = 16
MAX_MAPPING_NODES = 256
MAX_MAPPING_BYTES = 64 * 1024

POLICY_FORBIDDEN_OPERATORS = frozenset({"event_field_matches", "evaluation_outcome_is"})
EVALUATION_FORBIDDEN_OPERATORS = POLICY_FORBIDDEN_OPERATORS

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
ReasonCodeV1 = Annotated[
    str,
    StringConstraints(min_length=1, pattern=r"^[A-Z][A-Z0-9_]*$"),
]
NonEmptyString = Annotated[str, StringConstraints(min_length=1)]

type RiskLevel = Literal["low", "medium", "high", "critical"]
type ActorKind = Literal["human", "agent", "service"]
type PolicyDecision = Literal["allow", "deny", "require_approval"]
type EvaluationOutcome = Literal["pass", "rework", "human_review", "fail"]
type Visibility = Literal["public", "private"]
type Cardinality = Literal["one_to_one", "one_to_many", "many_to_one", "many_to_many"]
type ResponsibilityKind = Literal["accountable", "contributor", "reviewer", "observer"]
type ExecutionPolicy = Literal["responsible_actor_only", "delegation_allowed", "autonomous"]
type InheritanceMode = Literal["none", "nearest", "merge"]
type StateCategory = Literal["open", "active", "success", "failure", "cancelled"]
type AssignmentMode = Literal["fixed", "elastic"]
type HumanReviewRejectAction = Literal["rework", "fail"]
type MisfirePolicy = Literal["fire_once", "skip"]
type ApprovalPurpose = Literal["command_policy", "execution_gate", "quality_review"]
type RetryableFailureClass = Literal[
    "dependency_error", "timeout", "infrastructure_error", "unknown"
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


def _condition_operators(node: ConditionNode) -> Iterable[str]:
    yield node.op
    if isinstance(node, LogicalExpr):
        for child in node.conditions:
            yield from _condition_operators(child)
    elif isinstance(node, NotExpr):
        yield from _condition_operators(node.condition)


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
        if len(canonical_json_bytes(self.model_dump(mode="json"))) > MAX_CONDITION_BYTES:
            raise PydanticCustomError(
                "CONDITION_SIZE_EXCEEDED",
                f"condition AST exceeds {MAX_CONDITION_BYTES} canonical JSON bytes",
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

    @field_validator("fields")
    @classmethod
    def require_nonempty_field_names(cls, value: dict[str, MappingNode]) -> dict[str, MappingNode]:
        if any(not key for key in value):
            raise PydanticCustomError(
                "MAPPING_FIELD_INVALID", "mapping object field names must not be empty"
            )
        return value


class ArrayMapping(StrictModel):
    op: Literal["array"]
    items: list[MappingNode]


MappingNode = Annotated[
    ConstMapping | FromMapping | CoalesceMapping | ObjectMapping | ArrayMapping,
    Field(discriminator="op"),
]


class MappingExprV1(RootModel[MappingNode]):
    @model_validator(mode="after")
    def validate_limits(self) -> MappingExprV1:
        count, depth = _mapping_size(self.root)
        if count > MAX_MAPPING_NODES:
            raise PydanticCustomError(
                "MAPPING_NODE_LIMIT_EXCEEDED",
                f"mapping AST exceeds {MAX_MAPPING_NODES} nodes",
            )
        if depth > MAX_MAPPING_DEPTH:
            raise PydanticCustomError(
                "MAPPING_DEPTH_EXCEEDED",
                f"mapping AST exceeds depth {MAX_MAPPING_DEPTH}",
            )
        if len(canonical_json_bytes(self.model_dump(mode="json"))) > MAX_MAPPING_BYTES:
            raise PydanticCustomError(
                "MAPPING_SIZE_EXCEEDED",
                f"mapping AST exceeds {MAX_MAPPING_BYTES} canonical JSON bytes",
            )
        return self


def _mapping_size(node: MappingNode) -> tuple[int, int]:
    if isinstance(node, CoalesceMapping):
        children = [_mapping_size(child) for child in node.values]
    elif isinstance(node, ObjectMapping):
        children = [_mapping_size(child) for child in node.fields.values()]
    elif isinstance(node, ArrayMapping):
        children = [_mapping_size(child) for child in node.items]
    else:
        return 1, 1
    return 1 + sum(count for count, _ in children), 1 + max(
        (depth for _, depth in children), default=0
    )


def _require_unique(values: Iterable[str], field_name: str) -> None:
    items = list(values)
    if len(items) != len(set(items)):
        raise PydanticCustomError(
            "DEFINITION_DUPLICATE_KEY", f"{field_name} contains duplicate values"
        )


def _reject_condition_operators(
    expressions: Iterable[ConditionExprV1], forbidden: frozenset[str], usage: str
) -> None:
    found = sorted(
        {
            operator
            for expression in expressions
            for operator in _condition_operators(expression.root)
            if operator in forbidden
        }
    )
    if found:
        raise PydanticCustomError(
            "CONDITION_OPERATOR_FORBIDDEN",
            f"operators {found} are forbidden for {usage}",
        )


class ScopeTypeV1(StrictModel):
    key: LocalKeyV1
    parent_types: list[LocalKeyV1]
    attributes_schema: SchemaProfileV1

    @field_validator("parent_types")
    @classmethod
    def unique_parents(cls, value: list[str]) -> list[str]:
        _require_unique(value, "parent_types")
        return value


class RelationshipTypeV1(StrictModel):
    key: LocalKeyV1
    from_scope_types: list[LocalKeyV1] = Field(min_length=1)
    to_scope_types: list[LocalKeyV1] = Field(min_length=1)
    cardinality: Cardinality
    directed: bool
    attributes_schema: SchemaProfileV1

    @field_validator("from_scope_types", "to_scope_types")
    @classmethod
    def unique_scope_references(cls, value: list[str]) -> list[str]:
        _require_unique(value, "scope type references")
        return value


class DomainPolicyDefaultsV1(StrictModel):
    unknown_action: PolicyDecision
    dangerous_action: PolicyDecision


class DomainPackageDefinitionV1(StrictModel):
    schema_version: Literal[1]
    definition_kind: Literal["domain_package"]
    key: KeyV1
    display_name: NonEmptyString
    scope_types: list[ScopeTypeV1] = Field(min_length=1)
    relationship_types: list[RelationshipTypeV1]
    policy_defaults: DomainPolicyDefaultsV1
    compatible_work_definition_keys: list[KeyV1]
    compatible_role_definition_keys: list[KeyV1]

    @model_validator(mode="after")
    def validate_references(self) -> DomainPackageDefinitionV1:
        scope_keys = [scope.key for scope in self.scope_types]
        relationship_keys = [relationship.key for relationship in self.relationship_types]
        _require_unique(scope_keys, "scope_types")
        _require_unique(relationship_keys, "relationship_types")
        _require_unique(self.compatible_work_definition_keys, "compatible_work_definition_keys")
        _require_unique(self.compatible_role_definition_keys, "compatible_role_definition_keys")
        known = set(scope_keys)
        parent_graph: dict[str, set[str]] = {}
        for scope in self.scope_types:
            unknown = set(scope.parent_types) - known
            if unknown:
                raise PydanticCustomError(
                    "DEFINITION_REFERENCE_UNKNOWN",
                    f"scope '{scope.key}' references unknown parents {sorted(unknown)}",
                )
            parent_graph[scope.key] = set(scope.parent_types)
        for relationship in self.relationship_types:
            unknown = (
                set(relationship.from_scope_types) | set(relationship.to_scope_types)
            ) - known
            if unknown:
                raise PydanticCustomError(
                    "DEFINITION_REFERENCE_UNKNOWN",
                    f"relationship '{relationship.key}' references unknown scopes "
                    f"{sorted(unknown)}",
                )

        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(key: str) -> None:
            if key in visiting:
                raise PydanticCustomError(
                    "DEFINITION_REFERENCE_CYCLE", f"scope parent graph contains a cycle at '{key}'"
                )
            if key in visited:
                return
            visiting.add(key)
            for parent in sorted(parent_graph[key]):
                visit(parent)
            visiting.remove(key)
            visited.add(key)

        for scope_key in sorted(parent_graph):
            visit(scope_key)
        return self


class RoleAuthorityV1(StrictModel):
    commands: list[KeyV1]
    tools: list[KeyV1]
    data_scopes: list[KeyV1]
    max_risk_level: RiskLevel
    budget_cents: int = Field(ge=0, le=1_000_000_000_000_000)

    @field_validator("commands", "tools", "data_scopes")
    @classmethod
    def unique_authority_keys(cls, value: list[str]) -> list[str]:
        _require_unique(value, "authority keys")
        return value


class RoleCollaborationV1(StrictModel):
    receives_from: list[LocalKeyV1]
    hands_off_to: list[LocalKeyV1]
    escalates_to: list[LocalKeyV1]

    @field_validator("receives_from", "hands_off_to", "escalates_to")
    @classmethod
    def unique_slot_keys(cls, value: list[str]) -> list[str]:
        _require_unique(value, "collaboration slot keys")
        return value


class RoleQualityBarV1(StrictModel):
    evaluation_rule_keys: list[LocalKeyV1]

    @field_validator("evaluation_rule_keys")
    @classmethod
    def unique_rule_keys(cls, value: list[str]) -> list[str]:
        _require_unique(value, "evaluation_rule_keys")
        return value


class RoleCapacityV1(StrictModel):
    max_active_work_items: int = Field(ge=1, le=10_000)


class RoleDefinitionV1(StrictModel):
    schema_version: Literal[1]
    definition_kind: Literal["role"]
    key: KeyV1
    display_name: NonEmptyString
    mission: NonEmptyString
    accountabilities: list[NonEmptyString] = Field(min_length=1)
    required_capabilities: list[KeyV1]
    authority: RoleAuthorityV1
    collaboration: RoleCollaborationV1
    quality_bar: RoleQualityBarV1
    capacity: RoleCapacityV1

    @field_validator("accountabilities", "required_capabilities")
    @classmethod
    def unique_role_lists(cls, value: list[str]) -> list[str]:
        _require_unique(value, "role list")
        return value


class RoleSlotV1(StrictModel):
    key: LocalKeyV1
    role_definition_key: KeyV1
    required: bool
    min_assignments: int = Field(ge=0)
    max_assignments: int = Field(ge=1)
    responsibility_kind: ResponsibilityKind
    execution_policy: ExecutionPolicy
    inheritance_mode: InheritanceMode
    allowed_actor_kinds: list[ActorKind] = Field(min_length=1)
    separation_of_duties_from: list[LocalKeyV1]
    required_for_commands: list[KeyV1]
    assignment_policy_keys: list[KeyV1]

    @model_validator(mode="after")
    def validate_assignments(self) -> RoleSlotV1:
        if self.min_assignments > self.max_assignments:
            raise PydanticCustomError(
                "DEFINITION_LIMIT_EXCEEDED", "min_assignments must not exceed max_assignments"
            )
        if (
            self.required or self.responsibility_kind == "accountable"
        ) and self.min_assignments < 1:
            raise PydanticCustomError(
                "DEFINITION_LIMIT_EXCEEDED",
                "required and accountable slots require min_assignments >= 1",
            )
        if self.key in self.separation_of_duties_from:
            raise PydanticCustomError(
                "DEFINITION_REFERENCE_INVALID", "a slot cannot separate duties from itself"
            )
        for field_name, values in (
            ("allowed_actor_kinds", self.allowed_actor_kinds),
            ("separation_of_duties_from", self.separation_of_duties_from),
            ("required_for_commands", self.required_for_commands),
            ("assignment_policy_keys", self.assignment_policy_keys),
        ):
            _require_unique(values, field_name)
        return self


class WorkStateV1(StrictModel):
    key: LocalKeyV1
    terminal: bool
    category: StateCategory

    @model_validator(mode="after")
    def validate_category(self) -> WorkStateV1:
        terminal_categories = {"success", "failure", "cancelled"}
        if self.terminal != (self.category in terminal_categories):
            raise PydanticCustomError(
                "STATE_CATEGORY_INVALID",
                "terminal states require success/failure/cancelled; "
                "non-terminal states require open/active",
            )
        return self


class RequestPlanEffectV1(StrictModel):
    type: Literal["request_plan"]


class StartRunEffectV1(StrictModel):
    type: Literal["start_run"]


class CancelRunEffectV1(StrictModel):
    type: Literal["cancel_run"]
    reason_code: ReasonCodeV1


class RequestEvaluationEffectV1(StrictModel):
    type: Literal["request_evaluation"]
    evaluation_rule_keys: list[LocalKeyV1] = Field(min_length=1)

    @field_validator("evaluation_rule_keys")
    @classmethod
    def unique_rule_keys(cls, value: list[str]) -> list[str]:
        _require_unique(value, "evaluation_rule_keys")
        return value


class RequestApprovalEffectV1(StrictModel):
    type: Literal["request_approval"]
    approval_purpose: ApprovalPurpose
    required_role_slots: list[LocalKeyV1]
    ttl_seconds: int = Field(ge=60, le=604_800)

    @field_validator("required_role_slots")
    @classmethod
    def unique_required_slots(cls, value: list[str]) -> list[str]:
        _require_unique(value, "required_role_slots")
        return value


class EmitEventEffectV1(StrictModel):
    type: Literal["emit_event"]
    event_type: KeyV1
    payload_mapping: MappingExprV1

    @field_validator("event_type")
    @classmethod
    def require_qualified_event_type(cls, value: str) -> str:
        if "." not in value:
            raise PydanticCustomError("EFFECT_PAYLOAD_INVALID", "event_type must contain a dot")
        return value


class CreateChildWorkEffectV1(StrictModel):
    type: Literal["create_child_work"]
    dependency_key: LocalKeyV1
    input_mapping: MappingExprV1


class ScheduleCommandEffectV1(StrictModel):
    type: Literal["schedule_command"]
    command_type: KeyV1
    delay_seconds: int = Field(ge=1, le=604_800)
    timezone: NonEmptyString
    misfire_policy: MisfirePolicy
    payload_mapping: MappingExprV1

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise PydanticCustomError(
                "EFFECT_PAYLOAD_INVALID", "timezone must be an IANA timezone"
            ) from exc
        return value


def _validate_effect_discriminator(value: object) -> object:
    effect_type = value.get("type") if isinstance(value, Mapping) else getattr(value, "type", None)
    allowed = {
        "request_plan",
        "start_run",
        "cancel_run",
        "request_evaluation",
        "request_approval",
        "emit_event",
        "create_child_work",
        "schedule_command",
    }
    if effect_type not in allowed:
        raise PydanticCustomError(
            "EFFECT_TYPE_UNSUPPORTED", "effect type is missing or unsupported"
        )
    return value


EffectV1 = Annotated[
    RequestPlanEffectV1
    | StartRunEffectV1
    | CancelRunEffectV1
    | RequestEvaluationEffectV1
    | RequestApprovalEffectV1
    | EmitEventEffectV1
    | CreateChildWorkEffectV1
    | ScheduleCommandEffectV1,
    Discriminator(
        "type",
        custom_error_type="EFFECT_TYPE_UNSUPPORTED",
        custom_error_message="effect type is not supported",
    ),
    BeforeValidator(_validate_effect_discriminator),
]


class WorkTransitionV1(StrictModel):
    key: LocalKeyV1
    command_type: KeyV1
    from_states: list[LocalKeyV1] = Field(alias="from", min_length=1)
    to: LocalKeyV1
    required_role_slots: list[LocalKeyV1]
    guards: list[ConditionExprV1]
    policy_keys: list[KeyV1]
    effects: list[EffectV1]

    @field_validator("from_states", "required_role_slots", "policy_keys")
    @classmethod
    def unique_transition_references(cls, value: list[str]) -> list[str]:
        _require_unique(value, "transition references")
        return value


class StateMachineV1(StrictModel):
    initial_state: LocalKeyV1
    states: list[WorkStateV1] = Field(min_length=1)
    transitions: list[WorkTransitionV1]


class PolicyBindingV1(StrictModel):
    key: LocalKeyV1
    applies_to_commands: list[KeyV1] = Field(min_length=1)
    when: list[ConditionExprV1]
    decision: PolicyDecision
    required_role_slots: list[LocalKeyV1]
    approval_ttl_seconds: int | None
    reason_code: ReasonCodeV1

    @model_validator(mode="after")
    def validate_policy(self) -> PolicyBindingV1:
        _require_unique(self.applies_to_commands, "applies_to_commands")
        _require_unique(self.required_role_slots, "required_role_slots")
        if self.decision == "require_approval":
            if not self.required_role_slots:
                raise PydanticCustomError(
                    "EFFECT_PAYLOAD_INVALID", "approval policy requires role slots"
                )
            if self.approval_ttl_seconds is None or not 60 <= self.approval_ttl_seconds <= 604_800:
                raise PydanticCustomError(
                    "EFFECT_PAYLOAD_INVALID", "approval policy ttl must be between 60 and 604800"
                )
        elif self.approval_ttl_seconds is not None:
            raise PydanticCustomError(
                "EFFECT_PAYLOAD_INVALID", "non-approval policy ttl must be null"
            )
        _reject_condition_operators(self.when, POLICY_FORBIDDEN_OPERATORS, "policy")
        return self


class PlanningProfileV1(StrictModel):
    mode: Literal["required"]
    max_nodes: int = Field(ge=1, le=256)
    max_parallel_nodes: int = Field(ge=1, le=64)
    max_replans: int = Field(ge=0, le=3)
    acceptance: Literal["required"]

    @model_validator(mode="after")
    def validate_parallelism(self) -> PlanningProfileV1:
        if self.max_parallel_nodes > self.max_nodes:
            raise PydanticCustomError(
                "PLANNING_PROFILE_INVALID", "max_parallel_nodes must not exceed max_nodes"
            )
        return self


class RetryPolicyV1(StrictModel):
    max_attempts: int = Field(ge=1, le=10)
    initial_interval_seconds: int = Field(ge=1, le=3_600)
    max_interval_seconds: int = Field(ge=1, le=86_400)
    backoff_multiplier_milli: int = Field(ge=1_000, le=10_000)
    retryable_failure_classes: list[RetryableFailureClass]

    @model_validator(mode="after")
    def validate_retry_policy(self) -> RetryPolicyV1:
        if self.max_interval_seconds < self.initial_interval_seconds:
            raise PydanticCustomError(
                "EXECUTION_PROFILE_INVALID",
                "max_interval_seconds must not be less than initial_interval_seconds",
            )
        _require_unique(self.retryable_failure_classes, "retryable_failure_classes")
        return self


class ExecutionProfileV1(StrictModel):
    run_timeout_seconds: int = Field(ge=60, le=604_800)
    node_timeout_seconds: int = Field(ge=1, le=86_400)
    heartbeat_timeout_seconds: int | None = Field(ge=1)
    max_parallel_nodes: int = Field(ge=1, le=64)
    max_rework_attempts: int = Field(ge=0, le=10)
    retry_policy: RetryPolicyV1

    @model_validator(mode="after")
    def validate_timeouts(self) -> ExecutionProfileV1:
        if self.node_timeout_seconds > self.run_timeout_seconds:
            raise PydanticCustomError(
                "EXECUTION_PROFILE_INVALID", "node timeout must not exceed run timeout"
            )
        if (
            self.heartbeat_timeout_seconds is not None
            and self.heartbeat_timeout_seconds > self.node_timeout_seconds
        ):
            raise PydanticCustomError(
                "EXECUTION_PROFILE_INVALID", "heartbeat timeout must not exceed node timeout"
            )
        return self


class EvaluationRuleV1(StrictModel):
    key: LocalKeyV1
    when: list[ConditionExprV1] = Field(min_length=1)
    outcome: EvaluationOutcome
    reason_code: ReasonCodeV1
    required_evidence_paths: list[PathV1]

    @model_validator(mode="after")
    def validate_rule(self) -> EvaluationRuleV1:
        serialized_paths = [path.root for path in self.required_evidence_paths]
        _require_unique(serialized_paths, "required_evidence_paths")
        _reject_condition_operators(self.when, EVALUATION_FORBIDDEN_OPERATORS, "evaluation")
        return self


class ChildDependencyV1(StrictModel):
    dependency_key: LocalKeyV1
    work_definition_key: KeyV1
    allowed_scope_types: list[LocalKeyV1] = Field(min_length=1)

    @field_validator("allowed_scope_types")
    @classmethod
    def unique_scope_types(cls, value: list[str]) -> list[str]:
        _require_unique(value, "allowed_scope_types")
        return value


class TriggerCommandV1(StrictModel):
    command_type: KeyV1
    payload_mapping: MappingExprV1
    child_bundle_dependency_key: LocalKeyV1 | None

    @model_validator(mode="after")
    def validate_dependency_presence(self) -> TriggerCommandV1:
        is_child_command = self.command_type == "create_child_work"
        if is_child_command != (self.child_bundle_dependency_key is not None):
            raise PydanticCustomError(
                "TRIGGER_COMMAND_INVALID",
                "create_child_work requires a dependency key and all other commands require null",
            )
        return self


class TriggerV1(StrictModel):
    key: LocalKeyV1
    on_event: KeyV1
    conditions: list[ConditionExprV1]
    emit_command: TriggerCommandV1
    max_fires_per_correlation: int = Field(ge=1, le=32)

    @field_validator("on_event")
    @classmethod
    def require_qualified_event_type(cls, value: str) -> str:
        if "." not in value:
            raise PydanticCustomError("TRIGGER_COMMAND_INVALID", "on_event must contain a dot")
        return value


class WorkDefinitionV1(StrictModel):
    schema_version: Literal[1]
    definition_kind: Literal["work"]
    key: KeyV1
    display_name: NonEmptyString
    supported_scope_types: list[LocalKeyV1] = Field(min_length=1)
    input_schema: SchemaProfileV1
    result_schema: SchemaProfileV1
    assignment_mode: AssignmentMode
    role_slots: list[RoleSlotV1]
    state_machine: StateMachineV1
    policy_bindings: list[PolicyBindingV1]
    planning_profile: PlanningProfileV1
    execution_profile: ExecutionProfileV1
    evaluation_rules: list[EvaluationRuleV1] = Field(min_length=1)
    evaluation_default_outcome: EvaluationOutcome
    human_review_reject_action: HumanReviewRejectAction
    child_dependencies: list[ChildDependencyV1]
    triggers: list[TriggerV1]

    @model_validator(mode="after")
    def validate_definition(self) -> WorkDefinitionV1:
        _require_unique(self.supported_scope_types, "supported_scope_types")
        groups: tuple[tuple[str, list[str]], ...] = (
            ("role_slots", [item.key for item in self.role_slots]),
            ("states", [item.key for item in self.state_machine.states]),
            ("transitions", [item.key for item in self.state_machine.transitions]),
            (
                "transition command types",
                [item.command_type for item in self.state_machine.transitions],
            ),
            ("policy_bindings", [item.key for item in self.policy_bindings]),
            ("evaluation_rules", [item.key for item in self.evaluation_rules]),
            ("child_dependencies", [item.dependency_key for item in self.child_dependencies]),
            ("triggers", [item.key for item in self.triggers]),
        )
        for name, values in groups:
            _require_unique(values, name)

        slot_keys = {slot.key for slot in self.role_slots}
        state_keys = {state.key for state in self.state_machine.states}
        policy_keys = {policy.key for policy in self.policy_bindings}
        evaluation_keys = {rule.key for rule in self.evaluation_rules}
        dependency_keys = {dependency.dependency_key for dependency in self.child_dependencies}
        if not any(slot.responsibility_kind == "accountable" for slot in self.role_slots):
            raise PydanticCustomError(
                "DEFINITION_REFERENCE_UNKNOWN", "at least one accountable role slot is required"
            )
        for slot in self.role_slots:
            self._require_known(
                slot.separation_of_duties_from, slot_keys, f"slot '{slot.key}' separation_of_duties"
            )
        if self.state_machine.initial_state not in state_keys:
            raise PydanticCustomError("STATE_UNKNOWN", "initial_state is unknown")
        if not any(state.terminal for state in self.state_machine.states):
            raise PydanticCustomError("STATE_UNKNOWN", "at least one terminal state is required")

        for transition in self.state_machine.transitions:
            self._require_known(
                transition.from_states, state_keys, f"transition '{transition.key}' from"
            )
            self._require_known([transition.to], state_keys, f"transition '{transition.key}' to")
            self._require_known(
                transition.required_role_slots,
                slot_keys,
                f"transition '{transition.key}' role slots",
            )
            self._require_known(
                transition.policy_keys, policy_keys, f"transition '{transition.key}' policies"
            )
            for effect in transition.effects:
                if isinstance(effect, RequestEvaluationEffectV1):
                    self._require_known(
                        effect.evaluation_rule_keys,
                        evaluation_keys,
                        f"transition '{transition.key}' evaluation rules",
                    )
                elif isinstance(effect, RequestApprovalEffectV1):
                    self._require_known(
                        effect.required_role_slots,
                        slot_keys,
                        f"transition '{transition.key}' approval role slots",
                    )
                elif isinstance(effect, CreateChildWorkEffectV1):
                    self._require_known(
                        [effect.dependency_key],
                        dependency_keys,
                        f"transition '{transition.key}' child dependency",
                    )
        for policy in self.policy_bindings:
            self._require_known(
                policy.required_role_slots, slot_keys, f"policy '{policy.key}' role slots"
            )
        for trigger in self.triggers:
            dependency = trigger.emit_command.child_bundle_dependency_key
            if dependency is not None:
                self._require_known(
                    [dependency], dependency_keys, f"trigger '{trigger.key}' child dependency"
                )
        if self.execution_profile.max_parallel_nodes > self.planning_profile.max_parallel_nodes:
            raise PydanticCustomError(
                "EXECUTION_PROFILE_INVALID",
                "execution max_parallel_nodes must not exceed planning max_parallel_nodes",
            )
        return self

    @staticmethod
    def _require_known(values: Iterable[str], known: set[str], context: str) -> None:
        unknown = set(values) - known
        if unknown:
            raise PydanticCustomError(
                "DEFINITION_REFERENCE_UNKNOWN", f"{context} references {sorted(unknown)}"
            )


def _validate_definition_discriminator(value: object) -> object:
    kind = (
        value.get("definition_kind")
        if isinstance(value, Mapping)
        else getattr(value, "definition_kind", None)
    )
    if kind not in {"domain_package", "role", "work"}:
        raise PydanticCustomError(
            "DEFINITION_KIND_MISMATCH", "definition_kind is missing or unsupported"
        )
    return value


DefinitionV1 = Annotated[
    DomainPackageDefinitionV1 | RoleDefinitionV1 | WorkDefinitionV1,
    Discriminator(
        "definition_kind",
        custom_error_type="DEFINITION_KIND_MISMATCH",
        custom_error_message="definition_kind is missing or unsupported",
    ),
    BeforeValidator(_validate_definition_discriminator),
]
DEFINITION_V1_ADAPTER: TypeAdapter[DefinitionV1] = TypeAdapter(DefinitionV1)


def definition_checksum(definition: DefinitionV1) -> str:
    """Return the checksum of the complete validated Definition JSON."""

    from polis.modules.kernel.domain.canonical import canonical_checksum

    return canonical_checksum(definition.model_dump(mode="json", by_alias=True))


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
    "ChildDependencyV1",
    "ConditionExprV1",
    "ConditionNode",
    "DEFINITION_V1_ADAPTER",
    "DefinitionV1",
    "DomainPackageDefinitionV1",
    "EffectV1",
    "EvaluationRuleV1",
    "ExecutionProfileV1",
    "KeyV1",
    "LocalKeyV1",
    "MappingExprV1",
    "MappingNode",
    "PathV1",
    "PlanningProfileV1",
    "PolicyBindingV1",
    "ReasonCodeV1",
    "RoleDefinitionV1",
    "RoleSlotV1",
    "SchemaProfileV1",
    "StateMachineV1",
    "TriggerV1",
    "WorkDefinitionV1",
    "definition_checksum",
    "validate_semver",
]
