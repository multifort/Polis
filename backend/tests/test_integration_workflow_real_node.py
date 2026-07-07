"""TD-022：真实 Temporal worker 执行 run_node(stub=False) 并写回 DB。"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from polis.config import get_settings
from polis.db.session import dispose_engine
from polis.modules.org import provisioning
from polis.modules.org import repository as org_repo
from polis.modules.org import service as org_service
from polis.modules.org.schemas import ProvisionIn, RegisterIn
from polis.modules.planner import repository as repo
from polis.modules.planner.workflow import (
    TASK_QUEUE,
    TaskWorkflow,
    escalate_node,
    evaluate_node,
    finalize_run,
    generate_replan_subdag,
    run_node,
)
from polis.seed import seed


def _skip_if_temporal_unavailable() -> None:
    """Temporal test server 首次可能需要下载二进制；不可用时按集成测试策略跳过。"""
    try:
        from temporalio.testing import WorkflowEnvironment  # noqa: F401
    except ImportError as exc:  # pragma: no cover
        pytest.skip(f"temporalio 不可用：{exc}")


def _db_snapshot(pg_url: str, org_id: str, run_id: str) -> dict[str, Any]:
    engine = create_engine(pg_url.replace("+asyncpg", "+psycopg2"))
    try:
        with engine.connect() as conn:
            env = (
                conn.execute(
                    text(
                        """
                    SELECT node_id, status, summary, content, task_id
                    FROM result_envelope
                    WHERE org_id = :org_id AND task_id = :run_id
                    ORDER BY created_at
                    """
                    ),
                    {"org_id": org_id, "run_id": run_id},
                )
                .mappings()
                .all()
            )
            inv = (
                conn.execute(
                    text(
                        """
                    SELECT status, latency_ms
                    FROM skill_invocation
                    WHERE org_id = :org_id
                    ORDER BY created_at
                    """
                    ),
                    {"org_id": org_id},
                )
                .mappings()
                .all()
            )
            run = (
                conn.execute(
                    text("SELECT status, finished_at FROM task_run WHERE id = :run_id"),
                    {"run_id": run_id},
                )
                .mappings()
                .first()
            )
            plan = (
                conn.execute(
                    text(
                        """
                    SELECT p.status
                    FROM plan p
                    JOIN task_run r ON r.plan_id = p.id
                    WHERE r.id = :run_id
                    """
                    ),
                    {"run_id": run_id},
                )
                .mappings()
                .first()
            )
    finally:
        engine.dispose()
    return {
        "envelopes": [dict(row) for row in env],
        "invocations": [dict(row) for row in inv],
        "run": dict(run) if run is not None else None,
        "plan": dict(plan) if plan is not None else None,
    }


def test_temporal_worker_real_run_node_writes_envelope(
    pg_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """经 Temporal Worker 启动真实 run_node，而不是直接调用 execute_node。"""
    _skip_if_temporal_unavailable()
    monkeypatch.setenv("POLIS_DEEPSEEK_API_KEY", "")
    get_settings.cache_clear()

    workflow_id = f"test-real-run-node-{uuid.uuid4().hex}"

    plan = {
        "workflow_name": "td022_real_worker",
        "goal": "验证真实 worker 通过采购询价节点写入结果信封",
        "budget_cents": 50000,
        "nodes": [
            {
                "id": "n1",
                "type": "agent",
                "deps": [],
                "required_capabilities": ["procurement.rfq"],
                "input_hint": "向供应商询价并输出简短比价结果",
                "expected_output": "询价结果",
            }
        ],
    }

    async def _prepare_run() -> tuple[str, str]:
        engine = create_async_engine(get_settings().database_url)
        try:
            session_factory = async_sessionmaker(engine, expire_on_commit=False)
            async with session_factory() as session:
                await seed()
                email = f"td022_{uuid.uuid4().hex[:8]}@polis.dev"
                await org_service.register(
                    session,
                    RegisterIn(email=email, password="secret123"),
                )
                user = await org_repo.get_user_by_email(session, email)
                assert user is not None
                provisioned = await provisioning.provision(
                    session,
                    user.id,
                    ProvisionIn(name="真实 Worker E2E", preset="采购分析公司"),
                )
                org_id = str(provisioned.org.id)
                plan_row = await repo.create_plan(
                    session,
                    uuid.UUID(org_id),
                    goal=plan["goal"],
                    dag=plan,
                    version="td022_real_worker",
                    estimated_cost_cents=200,
                )
                run = await repo.create_task_run(
                    session,
                    uuid.UUID(org_id),
                    plan_row.id,
                    workflow_id,
                    status="running",
                )
                await repo.update_plan_status(session, uuid.UUID(org_id), plan_row.id, "running")
                run_id = str(run.id)
                await session.commit()
                return org_id, run_id
        finally:
            await engine.dispose()

    async def _run_workflow(org_id: str, run_id: str) -> dict[str, Any]:
        from temporalio.testing import WorkflowEnvironment
        from temporalio.worker import Worker

        async with await WorkflowEnvironment.start_time_skipping() as env:  # noqa: SIM117
            async with Worker(
                env.client,
                task_queue=TASK_QUEUE,
                workflows=[TaskWorkflow],
                activities=[
                    run_node,
                    evaluate_node,
                    finalize_run,
                    escalate_node,
                    generate_replan_subdag,
                ],
            ):
                return await env.client.execute_workflow(
                    TaskWorkflow.run,
                    args=[plan, org_id, run_id],
                    id=workflow_id,
                    task_queue=TASK_QUEUE,
                )

    async def _run() -> tuple[str, str, dict[str, Any]]:
        try:
            org_id, run_id = await _prepare_run()
            return org_id, run_id, await _run_workflow(org_id, run_id)
        finally:
            await dispose_engine()

    org_id, run_id, result = asyncio.run(_run())

    assert result["status"] == "done"
    assert result["nodes"] == [{"id": "n1", "status": "done"}]

    snapshot = _db_snapshot(pg_url, org_id, run_id)
    assert snapshot["run"]["status"] == "done"
    assert snapshot["run"]["finished_at"] is not None
    assert snapshot["plan"]["status"] == "done"

    envelopes = snapshot["envelopes"]
    assert len(envelopes) == 1
    assert envelopes[0]["task_id"] == uuid.UUID(run_id)
    assert envelopes[0]["node_id"] == "n1"
    assert envelopes[0]["status"] == "done"
    assert "[stub]" in (envelopes[0]["summary"] or "")
    assert envelopes[0]["content"]

    invocations = snapshot["invocations"]
    assert len(invocations) >= 1
    assert any(row["status"] == "done" and row["latency_ms"] > 0 for row in invocations)
