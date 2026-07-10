"""B3 role-frequency live evidence gate tests."""

from __future__ import annotations

import uuid

from scripts.memory.role_frequency_gate import (
    MemoryFact,
    evaluate_gate,
    is_benchmark_org_name,
)


def _fact(
    *,
    org_id: uuid.UUID,
    content: str,
    namespace: str,
    confidence: float,
    provenance: dict[str, object],
    promoted_from: uuid.UUID | None,
) -> MemoryFact:
    return MemoryFact(
        memory_id=uuid.uuid4(),
        org_id=org_id,
        org_name="真实采购公司",
        content=content,
        namespace=namespace,
        confidence=confidence,
        provenance=provenance,
        promoted_from=promoted_from,
    )


def test_b3_gate_accepts_complete_task_role_org_evidence() -> None:
    org_id = uuid.uuid4()
    task_ids = [uuid.uuid4(), uuid.uuid4()]
    namespace = f"role:{uuid.uuid4()}"
    content = "供应商A近一个月交付准时率仅60%"
    role_fact = _fact(
        org_id=org_id,
        content=content,
        namespace=namespace,
        confidence=0.9,
        provenance={
            "kind": "task_distill_role",
            "task_ids": [str(task_id) for task_id in task_ids],
            "occurrence_count": 2,
        },
        promoted_from=task_ids[0],
    )
    org_fact = _fact(
        org_id=org_id,
        content=content,
        namespace="company",
        confidence=0.9,
        provenance={
            "kind": "role_frequency",
            "role_frequency": 2,
            "role_namespaces": [namespace],
        },
        promoted_from=task_ids[1],
    )

    summary = evaluate_gate(
        [org_fact],
        [role_fact],
        {(org_id, str(task_id)): "done" for task_id in task_ids},
    )

    assert summary.has_data is True
    assert summary.passed is True
    assert summary.valid_count == 1
    assert summary.checks[0].observed_frequency == 2
    assert summary.checks[0].done_task_count == 2
    payload = summary.to_json(org_id=org_id, include_benchmark=False)
    assert payload["status"] == "pass"
    assert content not in str(payload)


def test_b3_gate_rejects_inconsistent_or_unfinished_source_tasks() -> None:
    org_id = uuid.uuid4()
    task_ids = [uuid.uuid4(), uuid.uuid4()]
    namespace = "role:procurement"
    content = "供应商B账期为30天"
    role_fact = _fact(
        org_id=org_id,
        content=content,
        namespace=namespace,
        confidence=0.9,
        provenance={
            "task_ids": [str(task_id) for task_id in task_ids],
            "occurrence_count": 1,
        },
        promoted_from=task_ids[0],
    )
    org_fact = _fact(
        org_id=org_id,
        content=content,
        namespace="company",
        confidence=0.9,
        provenance={
            "kind": "role_frequency",
            "role_frequency": 3,
            "role_namespaces": [namespace],
        },
        promoted_from=task_ids[1],
    )

    summary = evaluate_gate(
        [org_fact],
        [role_fact],
        {
            (org_id, str(task_ids[0])): "done",
            (org_id, str(task_ids[1])): "running",
        },
    )

    assert summary.passed is False
    errors = summary.checks[0].errors
    assert any("occurrence_count mismatch" in error for error in errors)
    assert "observed role task frequency does not match provenance" in errors
    assert "one or more source tasks are missing, cross-org, or not done" in errors


def test_b3_gate_reports_no_data_without_role_frequency_fact() -> None:
    org_id = uuid.uuid4()
    ordinary_org_fact = _fact(
        org_id=org_id,
        content="普通公司记忆",
        namespace="company",
        confidence=0.9,
        provenance={"kind": "task_distill"},
        promoted_from=None,
    )

    summary = evaluate_gate([ordinary_org_fact], [], {})

    assert summary.has_data is False
    assert summary.status == "no_data"
    assert summary.passed is False


def test_b3_gate_marks_benchmark_org_names() -> None:
    assert is_benchmark_org_name("M7验收门-1783332151") is True
    assert is_benchmark_org_name("R4自然复用Smoke公司") is True
    assert is_benchmark_org_name("B3频次门Smoke公司") is True
    assert is_benchmark_org_name("真实采购公司") is False
    assert is_benchmark_org_name(None) is False
