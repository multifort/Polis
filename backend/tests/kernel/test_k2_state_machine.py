"""K2-T1 pure Work state-machine conformance tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest
from pydantic import ValidationError

from polis.modules.kernel.domain.expressions import ConditionFacts
from polis.modules.kernel.domain.state_machine import (
    EffectGenerationContext,
    ExecutionSignal,
    WorkStateSnapshot,
    evaluate_guards,
    evaluate_transition,
    generate_effect_intents,
    lookup_transition,
    resolve_execution_status,
    validate_guard_conditions,
    validate_state_machine_static,
    validate_work_state,
)
from polis.modules.kernel.errors import KernelProtocolError
from polis.modules.kernel.schemas import (
    ConditionExprV1,
    WorkDefinitionV1,
    WorkTransitionV1,
)

FIXTURE_PATH = (
    Path(__file__).parents[3]
    / "docs"
    / "design"
    / "v3"
    / "kernel"
    / "fixtures"
    / "generic-definition-set-v1.json"
)


def _fixture_works() -> list[WorkDefinitionV1]:
    fixture = cast(dict[str, Any], json.loads(FIXTURE_PATH.read_text()))
    return [WorkDefinitionV1.model_validate(work) for work in fixture["works"]]


def _generation() -> EffectGenerationContext:
    return EffectGenerationContext(
        work_item_id="work-1",
        target_version=7,
        correlation_id="correlation-1",
    )


def _context(*, include_inputs: bool = True) -> dict[str, Any]:
    return {
        "command": {
            "command_type": "test",
            "payload": {},
            "requested_at": "2026-07-23T10:00:00Z",
            "correlation_id": "correlation-1",
            "causation_id": "cause-1",
        },
        "work": {
            "id": "work-1",
            "version": 6,
            "lifecycle_state": "draft",
            "execution_status": "idle",
            "inputs": (
                {
                    "source_result_id": "result-1",
                    "subject_artifact_id": "artifact-1",
                    "risk_level": "low",
                }
                if include_inputs
                else {}
            ),
            "latest_result": {"id": "result-1", "facts": {"score": 0.8}},
        },
        "scope": {"id": "scope-1", "type_key": "workspace", "attributes": {}},
        "bundle": {
            "id": "bundle-1",
            "checksum": "a" * 64,
            "work_definition_key": "core.test",
        },
        "actor": {"kind": "human", "ref": "actor-1", "role_slots": ["owner"]},
        "capacity": {"org": {"available": 3}, "actors": {"actor-1": {"available": 1}}},
        "approval": {"id": "approval-1", "status": "approved", "purpose": "command_policy"},
    }


def _positive_state(
    transition: WorkTransitionV1,
    source: str,
) -> tuple[WorkStateSnapshot, str | None]:
    if transition.command_type in {"complete_work", "fail_work"}:
        return WorkStateSnapshot(source, "evaluating", "run-1"), None
    if transition.command_type == "start_work":
        return WorkStateSnapshot(source, "idle", None), "run-new"
    if transition.command_type == "cancel_work" and source == "working":
        return WorkStateSnapshot(source, "running", "run-1"), None
    return WorkStateSnapshot(source, "idle", None), None


def _facts_for(command_type: str) -> ConditionFacts:
    outcome = None
    if command_type == "complete_work":
        outcome = "pass"
    elif command_type == "fail_work":
        outcome = "fail"
    return ConditionFacts(
        filled_role_slots=frozenset({"owner", "worker"}),
        evaluation_outcome=outcome,
    )


def _expected_execution(command_type: str) -> str:
    return {
        "start_work": "queued",
        "complete_work": "succeeded",
        "fail_work": "failed",
        "cancel_work": "cancelled",
    }.get(command_type, "idle")


@pytest.mark.parametrize("definition", _fixture_works(), ids=lambda item: item.key)
def test_every_fixture_transition_source_has_positive_and_negative_paths(
    definition: WorkDefinitionV1,
) -> None:
    nonterminal_states = {
        state.key for state in definition.state_machine.states if not state.terminal
    }
    for transition in definition.state_machine.transitions:
        for source in transition.from_states:
            current, next_run_id = _positive_state(transition, source)
            result = evaluate_transition(
                definition,
                current,
                ExecutionSignal(command_type=transition.command_type),
                _context(),
                generation=_generation(),
                facts=_facts_for(transition.command_type),
                next_active_run_id=next_run_id,
            )

            assert result.transition_key == transition.key
            assert result.next_state.lifecycle_state == transition.to
            assert result.next_state.execution_status == _expected_execution(
                transition.command_type
            )
            assert [intent.effect_index for intent in result.effects] == list(
                range(len(transition.effects))
            )

        disallowed_source = next(iter(nonterminal_states - set(transition.from_states)))
        with pytest.raises(KernelProtocolError) as caught:
            lookup_transition(
                definition,
                command_type=transition.command_type,
                lifecycle_state=disallowed_source,
            )
        assert caught.value.code == "TRANSITION_NOT_ALLOWED"


@pytest.mark.parametrize("definition", _fixture_works(), ids=lambda item: item.key)
def test_every_guarded_fixture_transition_has_a_failing_guard_path(
    definition: WorkDefinitionV1,
) -> None:
    for transition in definition.state_machine.transitions:
        if not transition.guards:
            continue
        with pytest.raises(KernelProtocolError) as caught:
            evaluate_guards(
                transition,
                _context(include_inputs=False),
                facts=ConditionFacts(),
            )
        assert caught.value.code == "GUARD_NOT_SATISFIED"
        assert caught.value.path.endswith("/guards/0")


@pytest.mark.parametrize(
    ("current", "signal", "expected"),
    [
        ("idle", ExecutionSignal("start_work"), "queued"),
        ("queued", ExecutionSignal("record_run_started"), "running"),
        ("running", ExecutionSignal("pause_work"), "waiting"),
        ("waiting", ExecutionSignal("resume_work"), "running"),
        (
            "running",
            ExecutionSignal("record_run_outcome", outcome="succeeded"),
            "evaluating",
        ),
        (
            "waiting",
            ExecutionSignal("record_run_outcome", outcome="partial"),
            "evaluating",
        ),
        (
            "running",
            ExecutionSignal("record_run_outcome", outcome="failed"),
            "evaluating",
        ),
        (
            "waiting",
            ExecutionSignal("record_run_outcome", outcome="timed_out"),
            "evaluating",
        ),
        (
            "running",
            ExecutionSignal(
                "record_run_outcome",
                outcome="cancelled",
                failure_class="unexpected_cancel",
            ),
            "evaluating",
        ),
        ("evaluating", ExecutionSignal("record_evaluation"), "evaluating"),
        ("evaluating", ExecutionSignal("complete_work"), "succeeded"),
        ("evaluating", ExecutionSignal("request_rework"), "idle"),
        ("evaluating", ExecutionSignal("request_human_review"), "waiting"),
        ("evaluating", ExecutionSignal("fail_work"), "failed"),
        ("idle", ExecutionSignal("cancel_work"), "cancelled"),
        ("queued", ExecutionSignal("cancel_work"), "cancelled"),
        ("running", ExecutionSignal("cancel_work"), "cancelled"),
        ("waiting", ExecutionSignal("cancel_work"), "cancelled"),
        ("evaluating", ExecutionSignal("cancel_work"), "cancelled"),
    ],
)
def test_fixed_execution_matrix(
    current: Any,
    signal: ExecutionSignal,
    expected: str,
) -> None:
    assert resolve_execution_status(current, signal) == expected


def test_execution_matrix_rejects_bad_discriminators_and_preconditions() -> None:
    assert (
        resolve_execution_status(
            "cancelled", ExecutionSignal("record_run_outcome", outcome="cancelled")
        )
        == "cancelled"
    )
    assert resolve_execution_status("idle", ExecutionSignal("custom_command")) == "idle"

    with pytest.raises(KernelProtocolError, match="requires an outcome"):
        resolve_execution_status("running", ExecutionSignal("record_run_outcome"))
    with pytest.raises(KernelProtocolError, match="does not match"):
        resolve_execution_status(
            "running",
            ExecutionSignal(
                "record_run_outcome",
                outcome="cancelled",
                failure_class="business_error",
            ),
        )
    with pytest.raises(KernelProtocolError, match="not allowed from"):
        resolve_execution_status("idle", ExecutionSignal("pause_work"))


def test_dual_state_validation_covers_categories_and_active_run_equivalence() -> None:
    definition = _fixture_works()[0]
    valid = (
        WorkStateSnapshot("draft", "idle", None),
        WorkStateSnapshot("working", "running", "run-1"),
        WorkStateSnapshot("completed", "succeeded", None),
        WorkStateSnapshot("failed", "failed", None),
        WorkStateSnapshot("cancelled", "cancelled", None),
    )
    for state in valid:
        validate_work_state(definition, state)

    invalid = (
        WorkStateSnapshot("missing", "idle", None),
        WorkStateSnapshot("draft", "succeeded", None),
        WorkStateSnapshot("completed", "idle", None),
        WorkStateSnapshot("working", "running", None),
        WorkStateSnapshot("working", "idle", "run-1"),
    )
    for state in invalid:
        with pytest.raises(KernelProtocolError):
            validate_work_state(definition, state)


def test_terminal_lifecycle_cannot_transition_out() -> None:
    definition = _fixture_works()[0]
    with pytest.raises(KernelProtocolError) as caught:
        lookup_transition(
            definition,
            command_type="submit_work",
            lifecycle_state="completed",
        )
    assert caught.value.code == "WORK_TERMINAL"


def test_guard_projection_allows_safe_subtrees_and_rejects_internal_fields() -> None:
    safe = [
        ConditionExprV1.model_validate({"op": "eq", "path": "/command/payload/value", "value": 1}),
        ConditionExprV1.model_validate({"op": "exists", "path": "/work/active_run_id"}),
        ConditionExprV1.model_validate(
            {"op": "gt", "path": "/capacity/actors/a/available", "value": 0}
        ),
        ConditionExprV1.model_validate({"op": "exists", "path": "/work/inputs"}),
        ConditionExprV1.model_validate(
            {
                "op": "all",
                "conditions": [
                    {"op": "input_exists", "path": "/work/inputs/document_id"},
                    {
                        "op": "not",
                        "condition": {
                            "op": "artifact_exists",
                            "path": "/work/result_ids/rejected",
                        },
                    },
                ],
            }
        ),
    ]
    validate_guard_conditions(safe)

    forbidden = (
        {"op": "eq", "path": "/actor/credentials", "value": "secret"},
        {"op": "eq", "path": "/event/payload/value", "value": 1},
        {"op": "input_exists", "path": "/scope/attributes/value"},
        {"op": "artifact_exists", "path": "/command/payload/artifact_id"},
        {
            "op": "event_field_matches",
            "path": "/event/type",
            "value": "work.completed",
        },
    )
    for raw in forbidden:
        condition = ConditionExprV1.model_validate(raw)
        with pytest.raises(KernelProtocolError):
            validate_guard_conditions([condition])


def test_static_validation_rejects_terminal_sources_target_mismatch_and_start_effects() -> None:
    definition = _fixture_works()[0]
    transitions = list(definition.state_machine.transitions)

    terminal_source = transitions[0].model_copy(update={"from_states": ["completed"]})
    changed = definition.model_copy(
        update={
            "state_machine": definition.state_machine.model_copy(
                update={"transitions": [terminal_source, *transitions[1:]]}
            )
        }
    )
    with pytest.raises(KernelProtocolError, match="terminal states"):
        validate_state_machine_static(changed)

    wrong_complete = transitions[2].model_copy(update={"to": "working"})
    changed = definition.model_copy(
        update={
            "state_machine": definition.state_machine.model_copy(
                update={"transitions": [*transitions[:2], wrong_complete, *transitions[3:]]}
            )
        }
    )
    with pytest.raises(KernelProtocolError, match="cannot target"):
        validate_state_machine_static(changed)

    start_without_effect = transitions[1].model_copy(update={"effects": []})
    changed = definition.model_copy(
        update={
            "state_machine": definition.state_machine.model_copy(
                update={
                    "transitions": [
                        transitions[0],
                        start_without_effect,
                        *transitions[2:],
                    ]
                }
            )
        }
    )
    with pytest.raises(KernelProtocolError, match="exactly one"):
        validate_state_machine_static(changed)

    start_on_submit = transitions[0].model_copy(update={"effects": transitions[1].effects})
    changed = definition.model_copy(
        update={
            "state_machine": definition.state_machine.model_copy(
                update={"transitions": [start_on_submit, *transitions[1:]]}
            )
        }
    )
    with pytest.raises(KernelProtocolError, match="only valid"):
        validate_state_machine_static(changed)


def test_static_validation_rejects_unreachable_states() -> None:
    definition = _fixture_works()[0]
    orphan = definition.state_machine.states[0].model_copy(update={"key": "orphan"})
    changed = definition.model_copy(
        update={
            "state_machine": definition.state_machine.model_copy(
                update={"states": [*definition.state_machine.states, orphan]}
            )
        }
    )
    with pytest.raises(KernelProtocolError, match="unreachable states"):
        validate_state_machine_static(changed)


def test_duplicate_transition_command_is_rejected_by_schema() -> None:
    raw = _fixture_works()[0].model_dump(mode="json", by_alias=True)
    raw["state_machine"]["transitions"][1]["command_type"] = "submit_work"
    with pytest.raises(ValidationError) as caught:
        WorkDefinitionV1.model_validate(raw)
    assert "TRANSITION_COMMAND_DUPLICATE" in {error["type"] for error in caught.value.errors()}


def test_all_effect_types_generate_ordered_closed_intents() -> None:
    transition = WorkTransitionV1.model_validate(
        {
            "key": "all_effects",
            "command_type": "custom_command",
            "from": ["draft"],
            "to": "ready",
            "required_role_slots": [],
            "guards": [],
            "policy_keys": [],
            "effects": [
                {"type": "request_plan"},
                {"type": "start_run"},
                {"type": "cancel_run", "reason_code": "USER_CANCELLED"},
                {
                    "type": "request_evaluation",
                    "evaluation_rule_keys": ["quality"],
                },
                {
                    "type": "request_approval",
                    "approval_purpose": "execution_gate",
                    "required_role_slots": ["owner"],
                    "ttl_seconds": 60,
                },
                {
                    "type": "emit_event",
                    "event_type": "work.custom",
                    "payload_mapping": {
                        "op": "object",
                        "fields": {
                            "version": {
                                "op": "from",
                                "path": "/work/version",
                                "required": True,
                            }
                        },
                    },
                },
                {
                    "type": "create_child_work",
                    "dependency_key": "child",
                    "input_mapping": {"op": "const", "value": {"subject": "a"}},
                },
                {
                    "type": "schedule_command",
                    "command_type": "follow_up",
                    "delay_seconds": 60,
                    "timezone": "Asia/Shanghai",
                    "misfire_policy": "fire_once",
                    "payload_mapping": {"op": "const", "value": {"attempt": 2}},
                },
            ],
        }
    )

    intents = generate_effect_intents(transition, _context(), generation=_generation())

    assert [intent.effect_type for intent in intents] == [
        "request_plan",
        "start_run",
        "cancel_run",
        "request_evaluation",
        "request_approval",
        "emit_event",
        "create_child_work",
        "schedule_command",
    ]
    assert intents[2].payload == {"reason_code": "USER_CANCELLED"}
    assert intents[3].payload == {"evaluation_rule_keys": ["quality"]}
    assert intents[4].payload["ttl_seconds"] == 60
    assert intents[5].payload == {"event_type": "work.custom", "payload": {"version": 6}}
    assert intents[6].payload == {
        "dependency_key": "child",
        "inputs": {"subject": "a"},
    }
    assert intents[7].payload["payload"] == {"attempt": 2}
    assert intents[7].schedule_key == "work-1:all_effects:7:7:correlation-1"
    assert all(intent.schedule_key is None for intent in intents[:-1])


def test_effect_mapping_root_cannot_leak_internal_missing_sentinel() -> None:
    transition = WorkTransitionV1.model_validate(
        {
            "key": "missing_mapping",
            "command_type": "custom_command",
            "from": ["draft"],
            "to": "ready",
            "required_role_slots": [],
            "guards": [],
            "policy_keys": [],
            "effects": [
                {
                    "type": "emit_event",
                    "event_type": "work.custom",
                    "payload_mapping": {
                        "op": "from",
                        "path": "/work/inputs/missing",
                        "required": False,
                    },
                }
            ],
        }
    )
    with pytest.raises(KernelProtocolError, match="cannot resolve to MISSING"):
        generate_effect_intents(transition, _context(), generation=_generation())


@pytest.mark.parametrize(
    "kwargs",
    [
        {"work_item_id": "", "target_version": 1, "correlation_id": "c"},
        {"work_item_id": "w", "target_version": 0, "correlation_id": "c"},
        {"work_item_id": "w", "target_version": 1, "correlation_id": ""},
    ],
)
def test_effect_generation_identity_is_never_partial(kwargs: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        EffectGenerationContext(**kwargs)
