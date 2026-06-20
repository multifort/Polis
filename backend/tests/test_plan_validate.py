"""单元测试（批次A / T3.1）：Plan 校验器拦截垃圾计划。纯逻辑，无 DB。"""

from __future__ import annotations

from polis.modules.planner.schemas import PlanDag, derive_overall_status, validate

CAPS = {"procurement.rfq", "procurement.supplier_analysis", "report.generation"}


def _dag(nodes: list[dict], budget: int = 0) -> PlanDag:
    return PlanDag(workflow_name="t", goal="g", budget_cents=budget, nodes=nodes)  # type: ignore[arg-type]


def test_valid_dag_passes() -> None:
    dag = _dag(
        [
            {"id": "n1", "type": "agent", "required_capabilities": ["procurement.rfq"]},
            {
                "id": "n2",
                "type": "agent",
                "deps": ["n1"],
                "required_capabilities": ["report.generation"],
            },
        ]
    )
    assert validate(dag, CAPS).ok


def test_cycle_rejected() -> None:
    dag = _dag(
        [
            {"id": "a", "deps": ["b"]},
            {"id": "b", "deps": ["a"]},
        ]
    )
    r = validate(dag, CAPS)
    assert not r.ok
    assert any("环" in e for e in r.errors)


def test_missing_dep_rejected() -> None:
    dag = _dag([{"id": "a", "deps": ["ghost"]}])
    assert not validate(dag, CAPS).ok


def test_unsatisfiable_capability_rejected() -> None:
    dag = _dag([{"id": "a", "type": "agent", "required_capabilities": ["nope.unknown"]}])
    r = validate(dag, CAPS)
    assert not r.ok
    assert any("能力" in e for e in r.errors)


def test_dangerous_must_be_human() -> None:
    dag = _dag([{"id": "a", "type": "agent", "dangerous": True}])
    r = validate(dag, CAPS)
    assert not r.ok
    assert any("危险" in e for e in r.errors)


def test_over_budget_rejected() -> None:
    dag = _dag([{"id": "a", "type": "agent"}], budget=1)  # agent=200 分 > 1
    r = validate(dag, CAPS)
    assert not r.ok
    assert any("预算" in e for e in r.errors)


# ── M3-C：顶层运行状态派生（GET /run 用，DB run.status 不自动更新） ──────────────


def test_overall_done_when_all_done() -> None:
    assert derive_overall_status(["done", "done", "done"]) == "done"


def test_overall_failed_when_any_failed() -> None:
    assert derive_overall_status(["done", "failed", "done"]) == "failed"


def test_overall_running_when_in_progress() -> None:
    assert derive_overall_status(["done", "running", "pending"]) == "running"


def test_overall_running_when_waiting_human() -> None:
    # 人审挂起仍算运行中（不是终态）
    assert derive_overall_status(["done", "waiting_human"]) == "running"


def test_overall_running_when_empty() -> None:
    assert derive_overall_status([]) == "running"
