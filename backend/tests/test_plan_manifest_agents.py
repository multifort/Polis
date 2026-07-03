"""Run Manifest agents_used 口径：记录实际路由到的 Agent 名称，而不是能力列表。"""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace
from typing import Any

import pytest

from polis.modules.planner import api as planner_api


def test_start_plan_manifest_records_routed_agents(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    org_id = uuid.uuid4()
    user_id = uuid.uuid4()
    plan_id = uuid.uuid4()
    run_id = uuid.uuid4()
    captured: dict[str, Any] = {}

    dag = {
        "workflow_name": "wf",
        "goal": "g",
        "budget_cents": 100,
        "nodes": [
            {
                "id": "n1",
                "type": "agent",
                "deps": [],
                "required_capabilities": ["market.sentiment"],
            }
        ],
    }
    plan = SimpleNamespace(id=plan_id, dag=dag, version="generated")

    class _TemporalClient:
        async def start_workflow(self, *_args: Any, **_kwargs: Any) -> None:
            captured["workflow_started"] = True

    async def _temporal_client() -> _TemporalClient:
        return _TemporalClient()

    async def _count_active_runs(*_args: Any, **_kwargs: Any) -> int:
        return 0

    async def _update_plan_status(*_args: Any, **_kwargs: Any) -> None:
        captured["plan_status_updated"] = True

    async def _create_task_run(*_args: Any, **_kwargs: Any) -> SimpleNamespace:
        return SimpleNamespace(id=run_id)

    async def _route_or_compose(*_args: Any, **_kwargs: Any) -> dict[str, str | None]:
        return {"n1": "弹性组队·market.sentiment"}

    async def _create_run_manifest(*_args: Any, **kwargs: Any) -> None:
        captured["manifest_agents"] = kwargs["agents_used"]

    async def _write_audit(*_args: Any, **_kwargs: Any) -> None:
        captured["audit_written"] = True

    monkeypatch.setattr(planner_api, "_temporal_client", _temporal_client)
    monkeypatch.setattr(planner_api.repo, "count_active_runs", _count_active_runs)
    monkeypatch.setattr(planner_api.repo, "update_plan_status", _update_plan_status)
    monkeypatch.setattr(planner_api.repo, "create_task_run", _create_task_run)
    monkeypatch.setattr(planner_api, "route_or_compose", _route_or_compose)
    monkeypatch.setattr(planner_api.obs_repo, "create_run_manifest", _create_run_manifest)
    monkeypatch.setattr(planner_api, "write_audit", _write_audit)

    async def _run() -> None:
        result = await planner_api._start_plan(
            SimpleNamespace(), org_id, plan, user_id, task_id=None
        )
        assert result.id == run_id

    asyncio.run(_run())

    assert captured["workflow_started"] is True
    assert captured["plan_status_updated"] is True
    assert captured["audit_written"] is True
    assert captured["manifest_agents"] == {"n1": "弹性组队·market.sentiment"}
