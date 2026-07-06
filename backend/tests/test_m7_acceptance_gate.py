"""M7/B 稳态验收 harness 的纯逻辑回归。"""

from __future__ import annotations

from pathlib import Path
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


def test_run_gate_uses_custom_goals_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    goals_file = tmp_path / "custom_goals.json"
    goals_file.write_text(
        """
        {
          "goals": [
            {
              "goal": "自定义目标",
              "acceptance": "应读取自定义目标集"
            }
          ]
        }
        """,
        encoding="utf-8",
    )

    class _FakeClient:
        def __init__(
            self, _base: str, _email: str, _password: str, _request_timeout: float
        ) -> None:
            self.org_id = ""

        def ensure_org(self, org_id: str | None) -> str:
            self.org_id = org_id or "org-test"
            return self.org_id

        def agents(self) -> dict[str, list[str]]:
            return {"报告Agent": ["report.generation"]}

        def relogin(self) -> None:
            return None

        def create_plan(self, goal: str) -> tuple[int, dict[str, Any]]:
            assert goal == "自定义目标"
            return (
                201,
                {
                    "id": "plan-test",
                    "template": "generated",
                    "dag": {
                        "nodes": [
                            {
                                "id": "n1",
                                "type": "agent",
                                "required_capabilities": ["report.generation"],
                            }
                        ]
                    },
                    "routing": {"n1": "报告Agent"},
                },
            )

    monkeypatch.setattr(acceptance_gate, "Gate", _FakeClient)
    args = type(
        "Args",
        (),
        {
            "goals_file": str(goals_file),
            "limit": 0,
            "base": "http://test",
            "email": "demo@polis.dev",
            "password": "secret123",
            "request_timeout": 120.0,
            "org_id": None,
            "full": False,
        },
    )()

    report = acceptance_gate.run_gate(args)
    assert report["metrics"]["goals"] == 1
    assert report["metrics"]["goals_file"] == str(goals_file)
    assert report["metrics"]["routing_hit_rate"] == 1.0
    assert report["rows"][0]["goal"] == "自定义目标"


def test_run_gate_keeps_going_when_one_goal_times_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    goals_file = tmp_path / "custom_goals.json"
    goals_file.write_text(
        """
        {
          "goals": [
            {"goal": "慢目标"},
            {"goal": "正常目标"}
          ]
        }
        """,
        encoding="utf-8",
    )

    class _FakeClient:
        def __init__(
            self, _base: str, _email: str, _password: str, _request_timeout: float
        ) -> None:
            self.org_id = ""

        def ensure_org(self, org_id: str | None) -> str:
            self.org_id = org_id or "org-test"
            return self.org_id

        def agents(self) -> dict[str, list[str]]:
            return {"报告Agent": ["report.generation"]}

        def relogin(self) -> None:
            return None

        def create_plan(self, goal: str) -> tuple[int, dict[str, Any]]:
            if goal == "慢目标":
                raise acceptance_gate.httpx.ReadTimeout("timed out")
            return (
                201,
                {
                    "id": "plan-test",
                    "template": "generated",
                    "dag": {
                        "nodes": [
                            {
                                "id": "n1",
                                "type": "agent",
                                "required_capabilities": ["report.generation"],
                            }
                        ]
                    },
                    "routing": {"n1": "报告Agent"},
                },
            )

    monkeypatch.setattr(acceptance_gate, "Gate", _FakeClient)
    args = type(
        "Args",
        (),
        {
            "goals_file": str(goals_file),
            "limit": 0,
            "base": "http://test",
            "email": "demo@polis.dev",
            "password": "secret123",
            "request_timeout": 120.0,
            "org_id": None,
            "full": False,
        },
    )()

    report = acceptance_gate.run_gate(args)
    assert report["metrics"]["goals"] == 2
    assert report["metrics"]["dag_available_rate"] == 0.5
    assert report["rows"][0]["dag_ok"] is False
    assert "ReadTimeout" in report["rows"][0]["error"]
    assert report["rows"][1]["dag_ok"] is True
