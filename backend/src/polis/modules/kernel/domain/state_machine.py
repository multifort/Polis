"""Pure lifecycle and execution-state evaluation for the V3 Work kernel."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from polis.modules.kernel.domain.expressions import (
    ConditionFacts,
    evaluate_condition,
    evaluate_mapping,
)
from polis.modules.kernel.domain.paths import MISSING, parse_path
from polis.modules.kernel.errors import KernelProtocolError
from polis.modules.kernel.schemas import (
    CancelRunEffectV1,
    CompareExpr,
    ConditionExprV1,
    ConditionNode,
    CreateChildWorkEffectV1,
    EffectV1,
    EmitEventEffectV1,
    EventExpr,
    ExistsExpr,
    LogicalExpr,
    MappingExprV1,
    NotExpr,
    RequestApprovalEffectV1,
    RequestEvaluationEffectV1,
    RequestPlanEffectV1,
    ScheduleCommandEffectV1,
    SetExpr,
    StartRunEffectV1,
    WorkDefinitionV1,
    WorkTransitionV1,
)

type ExecutionStatus = Literal[
    "idle",
    "queued",
    "running",
    "waiting",
    "evaluating",
    "succeeded",
    "failed",
    "cancelled",
]
type RunOutcome = Literal["succeeded", "partial", "failed", "timed_out", "cancelled"]

EXECUTION_STATUSES = frozenset(
    {"idle", "queued", "running", "waiting", "evaluating", "succeeded", "failed", "cancelled"}
)
ACTIVE_EXECUTION_STATUSES = frozenset({"queued", "running", "waiting", "evaluating"})
TERMINAL_EXECUTION_STATUSES = frozenset({"succeeded", "failed", "cancelled"})


@dataclass(frozen=True, slots=True)
class WorkStateSnapshot:
    """The state fields whose invariants are owned by the Work kernel."""

    lifecycle_state: str
    execution_status: ExecutionStatus
    active_run_id: str | None


@dataclass(frozen=True, slots=True)
class ExecutionSignal:
    """Discriminators needed to select one fixed execution transition."""

    command_type: str
    outcome: RunOutcome | None = None
    failure_class: str | None = None


@dataclass(frozen=True, slots=True)
class _ExecutionRule:
    command_type: str
    from_statuses: frozenset[ExecutionStatus]
    to_status: ExecutionStatus
    outcome: RunOutcome | None = None
    failure_class: str | None = None


EXECUTION_RULES: tuple[_ExecutionRule, ...] = (
    _ExecutionRule("start_work", frozenset({"idle"}), "queued"),
    _ExecutionRule("record_run_started", frozenset({"queued"}), "running"),
    _ExecutionRule("pause_work", frozenset({"running"}), "waiting"),
    _ExecutionRule("resume_work", frozenset({"waiting"}), "running"),
    _ExecutionRule(
        "record_run_outcome", frozenset({"running", "waiting"}), "evaluating", "succeeded"
    ),
    _ExecutionRule(
        "record_run_outcome", frozenset({"running", "waiting"}), "evaluating", "partial"
    ),
    _ExecutionRule("record_run_outcome", frozenset({"running", "waiting"}), "evaluating", "failed"),
    _ExecutionRule(
        "record_run_outcome", frozenset({"running", "waiting"}), "evaluating", "timed_out"
    ),
    _ExecutionRule(
        "record_run_outcome",
        frozenset({"running", "waiting"}),
        "evaluating",
        "cancelled",
        "unexpected_cancel",
    ),
    _ExecutionRule("record_evaluation", frozenset({"evaluating"}), "evaluating"),
    _ExecutionRule("complete_work", frozenset({"evaluating"}), "succeeded"),
    _ExecutionRule("request_rework", frozenset({"evaluating"}), "idle"),
    _ExecutionRule("request_human_review", frozenset({"evaluating"}), "waiting"),
    _ExecutionRule("fail_work", frozenset({"evaluating"}), "failed"),
    _ExecutionRule(
        "cancel_work",
        frozenset({"idle", "queued", "running", "waiting", "evaluating"}),
        "cancelled",
    ),
)

_COMMANDS_WITH_EXECUTION_RULES = frozenset(rule.command_type for rule in EXECUTION_RULES)
_TERMINAL_CATEGORY_STATUS: Mapping[str, ExecutionStatus] = {
    "success": "succeeded",
    "failure": "failed",
    "cancelled": "cancelled",
}
_TERMINAL_CATEGORY_COMMAND = {
    "success": "complete_work",
    "failure": "fail_work",
    "cancelled": "cancel_work",
}
_COMMAND_TARGET_CATEGORIES: Mapping[str, frozenset[str]] = {
    "start_work": frozenset({"active"}),
    "complete_work": frozenset({"success"}),
    "request_rework": frozenset({"open", "active"}),
    "request_human_review": frozenset({"open", "active"}),
    "fail_work": frozenset({"failure"}),
    "cancel_work": frozenset({"cancelled"}),
}

# Exact scalar paths and explicitly safe JSON subtrees exposed to a Work guard.
_GUARD_EXACT_PATHS = frozenset(
    {
        ("command", "command_type"),
        ("command", "requested_at"),
        ("command", "correlation_id"),
        ("command", "causation_id"),
        ("work", "id"),
        ("work", "version"),
        ("work", "lifecycle_state"),
        ("work", "execution_status"),
        ("work", "priority"),
        ("work", "due_at"),
        ("work", "input_revision"),
        ("work", "current_plan_id"),
        ("work", "active_run_id"),
        ("work", "latest_evaluation_id"),
        ("scope", "id"),
        ("scope", "type_key"),
        ("bundle", "id"),
        ("bundle", "checksum"),
        ("bundle", "work_definition_key"),
        ("actor", "kind"),
        ("actor", "ref"),
        ("approval", "id"),
        ("approval", "status"),
        ("approval", "purpose"),
    }
)
_GUARD_SUBTREE_PATHS = (
    ("command", "payload"),
    ("work", "inputs"),
    ("work", "result_ids"),
    ("scope", "attributes"),
    ("actor", "role_slots"),
    ("capacity", "org"),
    ("capacity", "actors"),
)


@dataclass(frozen=True, slots=True)
class EffectGenerationContext:
    """Stable identity inputs for deterministic effect intents."""

    work_item_id: str
    target_version: int
    correlation_id: str

    def __post_init__(self) -> None:
        if not self.work_item_id:
            raise ValueError("work_item_id must not be empty")
        if self.target_version < 1:
            raise ValueError("target_version must be positive")
        if not self.correlation_id:
            raise ValueError("correlation_id must not be empty")


@dataclass(frozen=True, slots=True)
class EffectIntent:
    """A side-effect-free instruction consumed by the later Outbox layer."""

    effect_index: int
    effect_type: str
    payload: Mapping[str, Any]
    schedule_key: str | None = None


@dataclass(frozen=True, slots=True)
class TransitionEvaluation:
    """Deterministic result of one declared Work lifecycle command."""

    transition_key: str
    previous_state: WorkStateSnapshot
    next_state: WorkStateSnapshot
    guard_results: tuple[bool, ...]
    effects: tuple[EffectIntent, ...]


def _condition_path(node: ConditionNode) -> str | None:
    if isinstance(node, (CompareExpr, SetExpr, ExistsExpr, EventExpr)):
        return node.path.root
    return None


def _guard_path_allowed(path: str) -> bool:
    tokens = parse_path(path)
    if tokens in _GUARD_EXACT_PATHS:
        return True
    return any(
        len(tokens) >= len(prefix) and tokens[: len(prefix)] == prefix
        for prefix in _GUARD_SUBTREE_PATHS
    )


def validate_guard_conditions(
    guards: Sequence[ConditionExprV1],
    *,
    path: str = "/guards",
) -> None:
    """Reject operators and data paths not exposed by the Work guard projection."""

    def visit(node: ConditionNode, node_path: str) -> None:
        if isinstance(node, EventExpr):
            raise KernelProtocolError(
                "CONDITION_OPERATOR_FORBIDDEN",
                node_path,
                "event_field_matches is trigger-only",
            )
        condition_path = _condition_path(node)
        if condition_path is not None and not _guard_path_allowed(condition_path):
            raise KernelProtocolError(
                "CONDITION_PATH_FORBIDDEN",
                f"{node_path}/path",
                f"Work guards cannot read '{condition_path}'",
            )
        if isinstance(node, ExistsExpr):
            tokens = parse_path(node.path.root)
            if node.op == "input_exists" and not (
                len(tokens) > 2 and tokens[:2] == ("work", "inputs")
            ):
                raise KernelProtocolError(
                    "CONDITION_PATH_FORBIDDEN",
                    f"{node_path}/path",
                    "input_exists requires a descendant of /work/inputs",
                )
            if node.op == "artifact_exists" and not (
                len(tokens) > 2 and tokens[:2] in {("work", "inputs"), ("work", "result_ids")}
            ):
                raise KernelProtocolError(
                    "CONDITION_PATH_FORBIDDEN",
                    f"{node_path}/path",
                    "artifact_exists requires a Work input or result descendant",
                )
        if isinstance(node, LogicalExpr):
            for index, child in enumerate(node.conditions):
                visit(child, f"{node_path}/conditions/{index}")
        elif isinstance(node, NotExpr):
            visit(node.condition, f"{node_path}/condition")

    for guard_index, guard in enumerate(guards):
        visit(guard.root, f"{path}/{guard_index}")


def evaluate_guards(
    transition: WorkTransitionV1,
    context: Mapping[str, Any],
    *,
    facts: ConditionFacts | None = None,
) -> tuple[bool, ...]:
    """Evaluate every guard in declaration order and fail at the first false result."""

    validate_guard_conditions(
        transition.guards,
        path=f"/state_machine/transitions/{transition.key}/guards",
    )
    results: list[bool] = []
    for index, guard in enumerate(transition.guards):
        result = evaluate_condition(guard, context, usage="guard", facts=facts)
        results.append(result)
        if not result:
            raise KernelProtocolError(
                "GUARD_NOT_SATISFIED",
                f"/state_machine/transitions/{transition.key}/guards/{index}",
                f"guard {index} for transition '{transition.key}' was not satisfied",
            )
    return tuple(results)


def lookup_transition(
    definition: WorkDefinitionV1,
    *,
    command_type: str,
    lifecycle_state: str,
) -> WorkTransitionV1:
    """Select the sole declared transition for a command and current lifecycle state."""

    states = {state.key: state for state in definition.state_machine.states}
    state = states.get(lifecycle_state)
    if state is None:
        raise KernelProtocolError("STATE_UNKNOWN", "/work/lifecycle_state", "state is not declared")
    if state.terminal:
        raise KernelProtocolError(
            "WORK_TERMINAL",
            "/work/lifecycle_state",
            f"terminal state '{lifecycle_state}' cannot transition",
        )
    candidates = [
        transition
        for transition in definition.state_machine.transitions
        if transition.command_type == command_type
    ]
    if len(candidates) > 1:
        raise KernelProtocolError(
            "BUNDLE_INCOMPATIBLE",
            "/state_machine/transitions",
            f"command '{command_type}' has ambiguous transitions",
        )
    if not candidates or lifecycle_state not in candidates[0].from_states:
        raise KernelProtocolError(
            "TRANSITION_NOT_ALLOWED",
            "/command/command_type",
            f"command '{command_type}' is not allowed from '{lifecycle_state}'",
        )
    return candidates[0]


def resolve_execution_status(
    current_status: ExecutionStatus,
    signal: ExecutionSignal,
) -> ExecutionStatus:
    """Apply the fixed execution matrix, leaving custom lifecycle commands unchanged."""

    if current_status not in EXECUTION_STATUSES:
        raise KernelProtocolError(
            "STATE_UNKNOWN", "/work/execution_status", "execution status is not supported"
        )
    if signal.command_type == "record_run_outcome" and signal.outcome is None:
        raise KernelProtocolError(
            "DEFINITION_INVALID",
            "/command/payload/outcome",
            "record_run_outcome requires an outcome discriminator",
        )
    if signal.command_type not in _COMMANDS_WITH_EXECUTION_RULES:
        return current_status

    matching = [
        rule
        for rule in EXECUTION_RULES
        if rule.command_type == signal.command_type
        and rule.outcome == signal.outcome
        and rule.failure_class == (signal.failure_class if rule.failure_class is not None else None)
    ]
    if (
        signal.command_type == "record_run_outcome"
        and signal.outcome == "cancelled"
        and signal.failure_class != "unexpected_cancel"
        and current_status == "cancelled"
    ):
        return "cancelled"
    if not matching:
        raise KernelProtocolError(
            "TRANSITION_NOT_ALLOWED",
            "/command",
            "execution signal does not match the fixed execution matrix",
        )
    rule = matching[0]
    if current_status not in rule.from_statuses:
        raise KernelProtocolError(
            "TRANSITION_NOT_ALLOWED",
            "/work/execution_status",
            f"command '{signal.command_type}' is not allowed from '{current_status}'",
        )
    return rule.to_status


def validate_work_state(definition: WorkDefinitionV1, state: WorkStateSnapshot) -> None:
    """Validate lifecycle category, execution status, and active-run invariants together."""

    state_definition = next(
        (item for item in definition.state_machine.states if item.key == state.lifecycle_state),
        None,
    )
    if state_definition is None:
        raise KernelProtocolError("STATE_UNKNOWN", "/work/lifecycle_state", "state is not declared")
    if state.execution_status not in EXECUTION_STATUSES:
        raise KernelProtocolError(
            "STATE_UNKNOWN", "/work/execution_status", "execution status is not supported"
        )

    expected_terminal_status = _TERMINAL_CATEGORY_STATUS.get(state_definition.category)
    if expected_terminal_status is not None and state.execution_status != expected_terminal_status:
        raise KernelProtocolError(
            "STATE_CATEGORY_INVALID",
            "/work/execution_status",
            f"{state_definition.category} lifecycle requires '{expected_terminal_status}'",
        )
    if expected_terminal_status is None and state.execution_status in TERMINAL_EXECUTION_STATUSES:
        raise KernelProtocolError(
            "STATE_CATEGORY_INVALID",
            "/work/execution_status",
            "open/active lifecycle cannot use a terminal execution status",
        )

    active_status = state.execution_status in ACTIVE_EXECUTION_STATUSES
    if active_status != (state.active_run_id is not None):
        raise KernelProtocolError(
            "STATE_CATEGORY_INVALID",
            "/work/active_run_id",
            "active_run_id must be present exactly for queued/running/waiting/evaluating",
        )


def validate_state_machine_static(
    definition: WorkDefinitionV1,
    *,
    path: str = "/state_machine",
) -> None:
    """Apply publish-time invariants that require the complete Work definition."""

    states = {state.key: state for state in definition.state_machine.states}
    transitions_by_command: dict[str, WorkTransitionV1] = {}
    for index, transition in enumerate(definition.state_machine.transitions):
        transition_path = f"{path}/transitions/{index}"
        if transition.command_type in transitions_by_command:
            raise KernelProtocolError(
                "BUNDLE_INCOMPATIBLE",
                f"{transition_path}/command_type",
                f"command '{transition.command_type}' has ambiguous transitions",
            )
        transitions_by_command[transition.command_type] = transition
        terminal_sources = sorted(
            source for source in transition.from_states if states[source].terminal
        )
        if terminal_sources:
            raise KernelProtocolError(
                "BUNDLE_INCOMPATIBLE",
                f"{transition_path}/from",
                f"terminal states cannot transition out: {terminal_sources}",
            )
        target = states[transition.to]
        allowed_categories = _COMMAND_TARGET_CATEGORIES.get(transition.command_type)
        if allowed_categories is not None and target.category not in allowed_categories:
            raise KernelProtocolError(
                "BUNDLE_INCOMPATIBLE",
                f"{transition_path}/to",
                f"command '{transition.command_type}' cannot target category '{target.category}'",
            )
        required_terminal_command = _TERMINAL_CATEGORY_COMMAND.get(target.category)
        if (
            required_terminal_command is not None
            and transition.command_type != required_terminal_command
        ):
            raise KernelProtocolError(
                "BUNDLE_INCOMPATIBLE",
                f"{transition_path}/command_type",
                f"category '{target.category}' requires command '{required_terminal_command}'",
            )
        start_effects = sum(isinstance(effect, StartRunEffectV1) for effect in transition.effects)
        if transition.command_type == "start_work" and start_effects != 1:
            raise KernelProtocolError(
                "BUNDLE_INCOMPATIBLE",
                f"{transition_path}/effects",
                "start_work requires exactly one start_run effect",
            )
        if transition.command_type != "start_work" and start_effects:
            raise KernelProtocolError(
                "BUNDLE_INCOMPATIBLE",
                f"{transition_path}/effects",
                "start_run is only valid on start_work",
            )
        validate_guard_conditions(transition.guards, path=f"{transition_path}/guards")

    reachable = {definition.state_machine.initial_state}
    changed = True
    while changed:
        changed = False
        for transition in definition.state_machine.transitions:
            if reachable.intersection(transition.from_states) and transition.to not in reachable:
                reachable.add(transition.to)
                changed = True
    unreachable = sorted(set(states) - reachable)
    if unreachable:
        raise KernelProtocolError(
            "BUNDLE_INCOMPATIBLE",
            path,
            f"state machine contains unreachable states {unreachable}",
        )


def _effect_payload(effect: EffectV1, context: Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(effect, (RequestPlanEffectV1, StartRunEffectV1)):
        return {}
    if isinstance(effect, CancelRunEffectV1):
        return {"reason_code": effect.reason_code}
    if isinstance(effect, RequestEvaluationEffectV1):
        return {"evaluation_rule_keys": list(effect.evaluation_rule_keys)}
    if isinstance(effect, RequestApprovalEffectV1):
        return {
            "approval_purpose": effect.approval_purpose,
            "required_role_slots": list(effect.required_role_slots),
            "ttl_seconds": effect.ttl_seconds,
        }
    if isinstance(effect, EmitEventEffectV1):
        return {
            "event_type": effect.event_type,
            "payload": _evaluate_effect_mapping(effect.payload_mapping, context),
        }
    if isinstance(effect, CreateChildWorkEffectV1):
        return {
            "dependency_key": effect.dependency_key,
            "inputs": _evaluate_effect_mapping(effect.input_mapping, context),
        }
    if isinstance(effect, ScheduleCommandEffectV1):
        return {
            "command_type": effect.command_type,
            "delay_seconds": effect.delay_seconds,
            "timezone": effect.timezone,
            "misfire_policy": effect.misfire_policy,
            "payload": _evaluate_effect_mapping(effect.payload_mapping, context),
        }
    raise AssertionError(f"unsupported effect: {type(effect).__name__}")


def _evaluate_effect_mapping(
    mapping: MappingExprV1,
    context: Mapping[str, Any],
) -> Any:
    value = evaluate_mapping(mapping, context)
    if value is MISSING:
        raise KernelProtocolError(
            "MAPPING_SOURCE_MISSING",
            "/effects",
            "an effect mapping root cannot resolve to MISSING",
        )
    return value


def generate_effect_intents(
    transition: WorkTransitionV1,
    context: Mapping[str, Any],
    *,
    generation: EffectGenerationContext,
) -> tuple[EffectIntent, ...]:
    """Evaluate declarative effects into ordered, persistence-neutral intents."""

    intents: list[EffectIntent] = []
    for index, effect in enumerate(transition.effects):
        schedule_key = None
        if isinstance(effect, ScheduleCommandEffectV1):
            schedule_key = (
                f"{generation.work_item_id}:{transition.key}:{index}:"
                f"{generation.target_version}:{generation.correlation_id}"
            )
        intents.append(
            EffectIntent(
                effect_index=index,
                effect_type=effect.type,
                payload=_effect_payload(effect, context),
                schedule_key=schedule_key,
            )
        )
    return tuple(intents)


def evaluate_transition(
    definition: WorkDefinitionV1,
    current_state: WorkStateSnapshot,
    signal: ExecutionSignal,
    context: Mapping[str, Any],
    *,
    generation: EffectGenerationContext,
    facts: ConditionFacts | None = None,
    next_active_run_id: str | None = None,
) -> TransitionEvaluation:
    """Evaluate one declared lifecycle transition without persistence or I/O."""

    validate_work_state(definition, current_state)
    transition = lookup_transition(
        definition,
        command_type=signal.command_type,
        lifecycle_state=current_state.lifecycle_state,
    )
    guard_results = evaluate_guards(transition, context, facts=facts)
    next_execution_status = resolve_execution_status(current_state.execution_status, signal)

    if signal.command_type == "start_work":
        active_run_id = next_active_run_id
    elif next_execution_status in {"idle", "succeeded", "failed", "cancelled"}:
        active_run_id = None
    else:
        active_run_id = current_state.active_run_id
    next_state = WorkStateSnapshot(
        lifecycle_state=transition.to,
        execution_status=next_execution_status,
        active_run_id=active_run_id,
    )
    validate_work_state(definition, next_state)

    source_work = context.get("work", {})
    if not isinstance(source_work, Mapping):
        raise KernelProtocolError(
            "DEFINITION_INVALID",
            "/work",
            "effect context Work projection must be an object",
        )
    work_projection = dict(source_work)
    work_projection.update(
        {
            "lifecycle_state": next_state.lifecycle_state,
            "execution_status": next_state.execution_status,
            "active_run_id": next_state.active_run_id,
            "version": generation.target_version,
        }
    )
    effect_context = {**context, "work": work_projection}
    effects = generate_effect_intents(transition, effect_context, generation=generation)
    return TransitionEvaluation(
        transition_key=transition.key,
        previous_state=current_state,
        next_state=next_state,
        guard_results=guard_results,
        effects=effects,
    )


__all__ = [
    "ACTIVE_EXECUTION_STATUSES",
    "EXECUTION_RULES",
    "EXECUTION_STATUSES",
    "EffectGenerationContext",
    "EffectIntent",
    "ExecutionSignal",
    "ExecutionStatus",
    "RunOutcome",
    "TERMINAL_EXECUTION_STATUSES",
    "TransitionEvaluation",
    "WorkStateSnapshot",
    "evaluate_guards",
    "evaluate_transition",
    "generate_effect_intents",
    "lookup_transition",
    "resolve_execution_status",
    "validate_guard_conditions",
    "validate_state_machine_static",
    "validate_work_state",
]
