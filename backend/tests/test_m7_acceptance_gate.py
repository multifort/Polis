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

    def signal(self, _plan_id: str, _node_id: str) -> int:
        return 204


def test_poll_until_terminal_accepts_needs_review(monkeypatch: pytest.MonkeyPatch) -> None:
    gate = _FakeGate(["running", "needs_review"])
    monkeypatch.setattr(acceptance_gate.time, "sleep", lambda _seconds: None)
    poll = acceptance_gate.poll_until_terminal(gate, "plan-1", timeout=1)
    assert poll.status == "needs_review"
    assert poll.human_signals == 0


def test_poll_until_terminal_auto_signals_waiting_human(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _HumanGate:
        def __init__(self) -> None:
            self.calls = 0
            self.signals: list[tuple[str, str]] = []

        def run(self, _plan_id: str) -> dict[str, Any]:
            self.calls += 1
            if self.calls == 1:
                return {"status": "running", "nodes": [{"id": "h1", "status": "waiting_human"}]}
            return {"status": "done", "nodes": [{"id": "h1", "status": "done"}]}

        def signal(self, plan_id: str, node_id: str) -> int:
            self.signals.append((plan_id, node_id))
            return 204

    gate = _HumanGate()
    monkeypatch.setattr(acceptance_gate.time, "sleep", lambda _seconds: None)

    poll = acceptance_gate.poll_until_terminal(gate, "plan-1", timeout=1)

    assert poll.status == "done"
    assert poll.human_signals == 1
    assert gate.signals == [("plan-1", "h1")]


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
            "non_terminal_runs": 0,
        }
    )
    out = capsys.readouterr().out
    assert "预算内 —" in out
    assert "B任务完成 : 0.0%" in out


def test_final_output_prefers_full_content_over_summary() -> None:
    out = acceptance_gate.final_output(
        {
            "nodes": [
                {"node_id": "n1", "summary": "上游摘要", "content": "上游全文"},
                {"node_id": "n2", "summary": "终端摘要", "content": "终端全文"},
            ]
        }
    )

    assert out == "终端全文"


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
            "auto_signal_human": True,
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
            "auto_signal_human": True,
        },
    )()

    report = acceptance_gate.run_gate(args)
    assert report["metrics"]["goals"] == 2
    assert report["metrics"]["dag_available_rate"] == 0.5
    assert report["rows"][0]["dag_ok"] is False
    assert "ReadTimeout" in report["rows"][0]["error"]
    assert report["rows"][1]["dag_ok"] is True


def test_run_gate_counts_non_terminal_full_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    goals_file = tmp_path / "custom_goals.json"
    goals_file.write_text('{"goals": [{"goal": "长跑目标"}]}', encoding="utf-8")

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

        def create_plan(self, _goal: str) -> tuple[int, dict[str, Any]]:
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

        def approve(self, _plan_id: str) -> int:
            return 201

        def run(self, _plan_id: str) -> dict[str, Any]:
            return {"status": "running"}

        def observability(self, _plan_id: str) -> dict[str, Any]:
            return {"totals": {"cost": 0}, "duration_seconds": None}

    monkeypatch.setattr(acceptance_gate, "Gate", _FakeClient)
    monkeypatch.setattr(
        acceptance_gate,
        "poll_until_terminal",
        lambda *_args, **_kwargs: acceptance_gate.PollResult("running"),
    )
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
            "full": True,
            "auto_signal_human": True,
            "timeout": 1.0,
            "latency_budget": 600.0,
        },
    )()

    report = acceptance_gate.run_gate(args)
    assert report["metrics"]["approved_runs"] == 1
    assert report["metrics"]["ran"] == 0
    assert report["metrics"]["task_completion_rate"] == 0.0
    assert report["metrics"]["non_terminal_runs"] == 1
    assert report["metrics"]["human_signals"] == 0
