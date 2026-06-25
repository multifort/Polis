"""M3-C 工作流测试：WorkflowEnvironment.start_time_skipping()（无需 docker Temporal）。

覆盖：
- 串/并全 done
- human 节点挂起 → signal → done
- fail_once 经 Temporal retry 成功
- fail_always × (MAX_REPLANS+1) 触发重规划上限 → overall failed
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import pytest

from polis.modules.planner.workflow import MAX_REPLANS, TASK_QUEUE, TaskWorkflow, run_node

# ── 辅助 ────────────────────────────────────────────────────────────────────


def _plan(nodes: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "workflow_name": "test_wf",
        "goal": "test",
        "budget_cents": 0,
        "nodes": nodes,
    }


def _node(
    nid: str,
    *,
    deps: list[str] | None = None,
    ntype: str = "agent",
    fail_once: bool = False,
    fail_always: bool = False,
    force_rework: bool = False,
    cap: str = "test.cap",
) -> dict[str, Any]:
    return {
        "id": nid,
        "type": ntype,
        "deps": deps or [],
        "required_capabilities": [cap] if ntype == "agent" else [],
        "executor": "lite-agent",
        "fail_once": fail_once,
        "fail_always": fail_always,
        "force_rework": force_rework,  # V2-S1 质量门测试钩子：强制不达标
        "stub": True,  # 纯编排测试走桩 run_node，不连 DB（M4-F）
    }


def _skip_if_unavailable() -> None:
    """首次运行会下载 Temporal 测试 server 二进制（需联网），离线时跳过。"""
    try:
        from temporalio.testing import WorkflowEnvironment  # noqa: F401
    except ImportError as exc:
        pytest.skip(f"temporalio 不可用：{exc}")


# ── 测试 ─────────────────────────────────────────────────────────────────────


def test_serial_parallel_all_done() -> None:
    """串/并节点全部成功完成。n1→n2,n3→n4（与 supplier_analysis 模板同构）。"""
    _skip_if_unavailable()

    async def _run() -> None:
        from temporalio.testing import WorkflowEnvironment
        from temporalio.worker import Worker

        plan = _plan(
            [
                _node("n1"),
                _node("n2", deps=["n1"]),
                _node("n3", deps=["n1"]),
                _node("n4", deps=["n2", "n3"]),
            ]
        )

        async with await WorkflowEnvironment.start_time_skipping() as env:  # noqa: SIM117
            async with Worker(
                env.client,
                task_queue=TASK_QUEUE,
                workflows=[TaskWorkflow],
                activities=[run_node],
            ):
                result: dict[str, Any] = await env.client.execute_workflow(
                    TaskWorkflow.run,
                    args=[plan, str(uuid.uuid4())],
                    id=f"test-serial-parallel-{uuid.uuid4().hex}",
                    task_queue=TASK_QUEUE,
                )

        assert result["status"] == "done"
        statuses = {n["id"]: n["status"] for n in result["nodes"]}
        assert all(s == "done" for s in statuses.values()), statuses

    asyncio.run(_run())


def test_human_node_signal() -> None:
    """human 节点挂起，approve signal 后恢复并完成。"""
    _skip_if_unavailable()

    async def _run() -> None:
        from temporalio.testing import WorkflowEnvironment
        from temporalio.worker import Worker

        plan = _plan(
            [
                _node("n1"),
                _node("h1", ntype="human", deps=["n1"]),
            ]
        )

        async with await WorkflowEnvironment.start_time_skipping() as env:  # noqa: SIM117
            async with Worker(
                env.client,
                task_queue=TASK_QUEUE,
                workflows=[TaskWorkflow],
                activities=[run_node],
            ):
                wf_id = f"test-human-{uuid.uuid4().hex}"
                handle = await env.client.start_workflow(
                    TaskWorkflow.run,
                    args=[plan, str(uuid.uuid4())],
                    id=wf_id,
                    task_queue=TASK_QUEUE,
                )

                # 等 human 节点进入 waiting_human 再 signal
                async def _wait_human() -> None:
                    for _ in range(50):
                        raw: dict[str, Any] = await handle.query(TaskWorkflow.status)
                        if any(n["status"] == "waiting_human" for n in raw.get("nodes", [])):
                            return
                        await asyncio.sleep(0.1)

                await _wait_human()
                await handle.signal(TaskWorkflow.approve, "h1")
                result: dict[str, Any] = await handle.result()

        assert result["status"] == "done"
        statuses = {n["id"]: n["status"] for n in result["nodes"]}
        assert statuses["h1"] == "done"

    asyncio.run(_run())


def test_fail_once_retry_succeeds() -> None:
    """fail_once 节点首次失败，Temporal retry 后成功。"""
    _skip_if_unavailable()

    async def _run() -> None:
        from temporalio.testing import WorkflowEnvironment
        from temporalio.worker import Worker

        plan = _plan([_node("n1", fail_once=True)])

        async with await WorkflowEnvironment.start_time_skipping() as env:  # noqa: SIM117
            async with Worker(
                env.client,
                task_queue=TASK_QUEUE,
                workflows=[TaskWorkflow],
                activities=[run_node],
            ):
                result: dict[str, Any] = await env.client.execute_workflow(
                    TaskWorkflow.run,
                    args=[plan, str(uuid.uuid4())],
                    id=f"test-retry-{uuid.uuid4().hex}",
                    task_queue=TASK_QUEUE,
                )

        assert result["status"] == "done"
        assert result["nodes"][0]["status"] == "done"

    asyncio.run(_run())


def test_replan_limit_exceeded() -> None:
    """MAX_REPLANS+1 个 fail_always 节点耗尽重规划预算，workflow 整体 failed。"""
    _skip_if_unavailable()

    async def _run() -> None:
        from temporalio.testing import WorkflowEnvironment
        from temporalio.worker import Worker

        # MAX_REPLANS+1 个独立失败节点：前 MAX_REPLANS 个触发重规划，最后一个超限
        nodes = [
            _node(f"f{i}", fail_always=True, cap=f"test.cap{i}") for i in range(MAX_REPLANS + 1)
        ]
        plan = _plan(nodes)

        async with await WorkflowEnvironment.start_time_skipping() as env:  # noqa: SIM117
            async with Worker(
                env.client,
                task_queue=TASK_QUEUE,
                workflows=[TaskWorkflow],
                activities=[run_node],
            ):
                result: dict[str, Any] = await env.client.execute_workflow(
                    TaskWorkflow.run,
                    args=[plan, str(uuid.uuid4())],
                    id=f"test-replan-limit-{uuid.uuid4().hex}",
                    task_queue=TASK_QUEUE,
                )

        assert result["status"] == "failed"
        statuses = {n["id"]: n["status"] for n in result["nodes"]}
        assert all(s == "failed" for s in statuses.values()), statuses

    asyncio.run(_run())


def test_quality_gate_needs_review() -> None:
    """V2-S1 质量门：终端节点产出不达标 → 该节点 needs_rework、顶层 needs_review；其余 done。"""
    _skip_if_unavailable()

    async def _run() -> None:
        from temporalio.testing import WorkflowEnvironment
        from temporalio.worker import Worker

        from polis.modules.planner.workflow import evaluate_node

        plan = _plan(
            [
                _node("n1"),
                _node("n2", deps=["n1"]),
                _node("n4", deps=["n2"], force_rework=True),  # 关键节点质量不达标
            ]
        )

        async with await WorkflowEnvironment.start_time_skipping() as env:  # noqa: SIM117
            async with Worker(
                env.client,
                task_queue=TASK_QUEUE,
                workflows=[TaskWorkflow],
                activities=[run_node, evaluate_node],
            ):
                result: dict[str, Any] = await env.client.execute_workflow(
                    TaskWorkflow.run,
                    args=[plan, str(uuid.uuid4())],
                    id=f"test-quality-gate-{uuid.uuid4().hex}",
                    task_queue=TASK_QUEUE,
                )

        statuses = {n["id"]: n["status"] for n in result["nodes"]}
        assert result["status"] == "needs_review", result["status"]
        assert statuses["n4"] == "needs_rework", statuses
        assert statuses["n1"] == "done" and statuses["n2"] == "done", statuses

    asyncio.run(_run())
