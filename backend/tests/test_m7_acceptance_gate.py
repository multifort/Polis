"""M7/B 稳态验收 harness 的纯逻辑回归。"""

from __future__ import annotations

from typing import Any

import pytest
from scripts.m7 import acceptance_gate


class _FakeGate:
    def __init__(self, statuses: list[str]) -> None:
        self.statuses = statuses

    def run(self, _plan_id: str) -> dict[str, Any]:
        return {"status": self.statuses.pop(0)}


def test_poll_until_terminal_accepts_needs_review(monkeypatch: pytest.MonkeyPatch) -> None:
    gate = _FakeGate(["running", "needs_review"])
    monkeypatch.setattr(acceptance_gate.time, "sleep", lambda _seconds: None)
    assert acceptance_gate.poll_until_terminal(gate, "plan-1", timeout=1) == "needs_review"


def test_verdict_prints_budget_dash_without_done_runs(capsys: pytest.CaptureFixture[str]) -> None:
    acceptance_gate.verdict(
        {
            "dag_available_rate": 1.0,
            "routing_hit_rate": 1.0,
            "human_pass_rate": None,
            "avg_cost_yuan": 0.01,
            "avg_duration_s": 12.0,
            "within_budget_rate": None,
            "task_completion_rate": 0.0,
            "approved_runs": 2,
            "ran": 0,
            "needs_review_runs": 2,
            "failed_runs": 0,
        }
    )
    out = capsys.readouterr().out
    assert "预算内 —" in out
    assert "B任务完成 : 0.0%" in out
