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
from datetime import timedelta
from typing import Any

import pytest
from temporalio import activity

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
    dangerous: bool = False,
    fail_once: bool = False,
    fail_always: bool = False,
    force_rework: bool = False,
    rework_recover: bool = False,
    heartbeat_timeout_ms: int | None = None,
    local_replan: bool | None = None,
    local_replan_nodes: list[dict[str, Any]] | None = None,
    cap: str = "test.cap",
) -> dict[str, Any]:
    node = {
        "id": nid,
        "type": ntype,
        "deps": deps or [],
        "required_capabilities": [cap] if ntype == "agent" else [],
        "executor": "lite-agent",
        "dangerous": dangerous,
        "fail_once": fail_once,
        "fail_always": fail_always,
        "force_rework": force_rework,  # V2-S1 质量门测试钩子：强制不达标
        "rework_recover": rework_recover,  # V2-S2 测试钩子：首次不达标、返工即恢复
        "stub": True,  # 纯编排测试走桩 run_node，不连 DB（M4-F）
    }
    if heartbeat_timeout_ms is not None:
        node["heartbeat_timeout_ms"] = heartbeat_timeout_ms
    if local_replan is not None:
        node["local_replan"] = local_replan
    if local_replan_nodes is not None:
        node["local_replan_nodes"] = local_replan_nodes
    return node


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


def test_s2b_local_replan_replaces_failed_subgraph() -> None:
    """V2-S2b 局部重规划：替换失败节点及下游子图，已 done 上游不重跑。"""
    _skip_if_unavailable()

    async def _run() -> None:
        from temporalio.testing import WorkflowEnvironment
        from temporalio.worker import Worker

        replacement = [
            _node("n2b", deps=["n1"]),
            _node("n3", deps=["n2b"]),
        ]
        plan = _plan(
            [
                _node("n1"),
                _node("n2", deps=["n1"], fail_always=True, local_replan_nodes=replacement),
                _node("n3", deps=["n2"]),
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
                    id=f"test-s2b-local-replan-{uuid.uuid4().hex}",
                    task_queue=TASK_QUEUE,
                )

        statuses = {n["id"]: n["status"] for n in result["nodes"]}
        assert result["status"] == "done", result
        assert statuses == {"n1": "done", "n2b": "done", "n3": "done"}

    asyncio.run(_run())


def test_s2b_local_replan_can_call_generation_activity() -> None:
    """V2-S2b 在线策略：异常节点 opt-in 后由 Activity 生成 replacement nodes。"""
    _skip_if_unavailable()

    async def _run() -> None:
        from temporalio.testing import WorkflowEnvironment
        from temporalio.worker import Worker

        @activity.defn(name="generate_replan_subdag")
        async def fake_generate_replan_subdag(
            plan: dict[str, Any],
            failed_node_id: str,
            failure_reason: str,
            available_capabilities: list[str],
        ) -> list[dict[str, Any]]:
            assert failed_node_id == "n2"
            assert "Activity task failed" in failure_reason
            assert "test.cap" in available_capabilities
            assert plan["nodes"][1]["id"] == "n2"
            return [
                _node("n2b", deps=["n1"]),
                _node("n3", deps=["n2b"]),
            ]

        plan = _plan(
            [
                _node("n1"),
                _node("n2", deps=["n1"], fail_always=True, local_replan=True),
                _node("n3", deps=["n2"]),
            ]
        )

        async with await WorkflowEnvironment.start_time_skipping() as env:  # noqa: SIM117
            async with Worker(
                env.client,
                task_queue=TASK_QUEUE,
                workflows=[TaskWorkflow],
                activities=[run_node, fake_generate_replan_subdag],
            ):
                result: dict[str, Any] = await env.client.execute_workflow(
                    TaskWorkflow.run,
                    args=[plan, str(uuid.uuid4())],
                    id=f"test-s2b-local-replan-activity-{uuid.uuid4().hex}",
                    task_queue=TASK_QUEUE,
                )

        statuses = {n["id"]: n["status"] for n in result["nodes"]}
        assert result["status"] == "done", result
        assert statuses == {"n1": "done", "n2b": "done", "n3": "done"}

    asyncio.run(_run())


def test_s2b_local_replan_auto_for_failed_subgraph() -> None:
    """V2-S2b 自动策略：失败牵连下游子图时，无显式标记也调用在线局部重规划。"""
    _skip_if_unavailable()

    async def _run() -> None:
        from temporalio.testing import WorkflowEnvironment
        from temporalio.worker import Worker

        @activity.defn(name="generate_replan_subdag")
        async def fake_generate_replan_subdag(
            plan: dict[str, Any],
            failed_node_id: str,
            failure_reason: str,
            available_capabilities: list[str],
        ) -> list[dict[str, Any]]:
            assert failed_node_id == "n2"
            assert failure_reason
            assert "test.cap" in available_capabilities
            assert [n["id"] for n in plan["nodes"]] == ["n1", "n2", "n3"]
            return [
                _node("n2b", deps=["n1"]),
                _node("n3", deps=["n2b"]),
            ]

        plan = _plan(
            [
                _node("n1"),
                _node("n2", deps=["n1"], fail_always=True),
                _node("n3", deps=["n2"]),
            ]
        )

        async with await WorkflowEnvironment.start_time_skipping() as env:  # noqa: SIM117
            async with Worker(
                env.client,
                task_queue=TASK_QUEUE,
                workflows=[TaskWorkflow],
                activities=[run_node, fake_generate_replan_subdag],
            ):
                result: dict[str, Any] = await env.client.execute_workflow(
                    TaskWorkflow.run,
                    args=[plan, str(uuid.uuid4())],
                    id=f"test-s2b-local-replan-auto-{uuid.uuid4().hex}",
                    task_queue=TASK_QUEUE,
                )

        statuses = {n["id"]: n["status"] for n in result["nodes"]}
        assert result["status"] == "done", result
        assert statuses == {"n1": "done", "n2b": "done", "n3": "done"}

    asyncio.run(_run())


def test_s2b_auto_local_replan_skips_guarded_failure_types() -> None:
    """V2-S2b 自动策略边界：叶子/显式禁用/system/dangerous 不调用在线局部重规划。"""
    _skip_if_unavailable()

    async def _run() -> None:
        from temporalio.testing import WorkflowEnvironment
        from temporalio.worker import Worker

        called: list[str] = []

        @activity.defn(name="generate_replan_subdag")
        async def fake_generate_replan_subdag(
            _plan: dict[str, Any],
            failed_node_id: str,
            _failure_reason: str,
            _available_capabilities: list[str],
        ) -> list[dict[str, Any]]:
            called.append(failed_node_id)
            return [
                _node("n2b", deps=["n1"]),
                _node("n3", deps=["n2b"]),
            ]

        cases = {
            "leaf": [
                _node("n1"),
                _node("n2", deps=["n1"], fail_always=True),
            ],
            "disabled": [
                _node("n1"),
                _node("n2", deps=["n1"], fail_always=True, local_replan=False),
                _node("n3", deps=["n2"]),
            ],
            "system": [
                _node("n1"),
                _node("n2", deps=["n1"], ntype="system", fail_always=True),
                _node("n3", deps=["n2"]),
            ],
            "dangerous": [
                _node("n1"),
                _node("n2", deps=["n1"], dangerous=True, fail_always=True),
                _node("n3", deps=["n2"]),
            ],
        }

        async with await WorkflowEnvironment.start_time_skipping() as env:  # noqa: SIM117
            async with Worker(
                env.client,
                task_queue=TASK_QUEUE,
                workflows=[TaskWorkflow],
                activities=[run_node, fake_generate_replan_subdag],
            ):
                for label, nodes in cases.items():
                    result: dict[str, Any] = await env.client.execute_workflow(
                        TaskWorkflow.run,
                        args=[_plan(nodes), str(uuid.uuid4())],
                        id=f"test-s2b-local-replan-skip-{label}-{uuid.uuid4().hex}",
                        task_queue=TASK_QUEUE,
                    )
                    statuses = {n["id"]: n["status"] for n in result["nodes"]}
                    assert result["status"] == "failed", (label, result)
                    assert statuses["n2"] == "failed", (label, statuses)

        assert called == []

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
        assert result["quality"]["n4"] == 0.0
        assert result["quality_detail"]["n4"] == {
            "judge_scores": [0.0],
            "judge_policy": "test_hook",
        }

    asyncio.run(_run())


def test_s2_rework_recovers() -> None:
    """V2-S2 分级纠错 ②：关键节点首次不达标 → 反馈重跑【同节点】→ 达标 → done（自动纠错）。"""
    _skip_if_unavailable()

    async def _run() -> None:
        from temporalio.testing import WorkflowEnvironment
        from temporalio.worker import Worker

        from polis.modules.planner.workflow import evaluate_node

        plan = _plan(
            [
                _node("n1"),
                _node("n2", deps=["n1"], rework_recover=True),  # 首次不达标，返工即恢复
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
                    id=f"test-s2-rework-{uuid.uuid4().hex}",
                    task_queue=TASK_QUEUE,
                )

        statuses = {n["id"]: n["status"] for n in result["nodes"]}
        # 返工后达标 → 顶层全 done，n2 done（而非卡 needs_review）
        assert result["status"] == "done", result["status"]
        assert statuses["n2"] == "done", statuses

    asyncio.run(_run())


def test_s4_activity_heartbeat_timeout_recovers_workflow() -> None:
    """V2-S4 长任务恢复硬测：activity 停止心跳后，Temporal retry 并恢复 workflow。"""
    _skip_if_unavailable()

    async def _run() -> None:
        from temporalio.testing import WorkflowEnvironment
        from temporalio.worker import Worker

        first_attempt_started = asyncio.Event()
        attempts: list[str] = []

        @activity.defn(name="run_node")
        async def flaky_run_node(
            node: dict[str, Any], org_id: str, task_id: str = "", goal: str = ""
        ) -> dict[str, Any]:
            if not attempts:
                attempts.append("stalled")
                activity.heartbeat("started")
                first_attempt_started.set()
                await asyncio.sleep(1)
                return {
                    "node_id": node["id"],
                    "ok": False,
                    "agent": "stalled",
                    "output": "stale",
                }
            attempts.append("recovered")
            return {
                "node_id": node["id"],
                "ok": True,
                "agent": "recovered-worker",
                "output": f"[recovered] node {node['id']} done",
            }

        plan = _plan([_node("n1", heartbeat_timeout_ms=100)])

        async with await WorkflowEnvironment.start_time_skipping() as env:  # noqa: SIM117
            async with Worker(
                env.client,
                task_queue=TASK_QUEUE,
                workflows=[TaskWorkflow],
                activities=[flaky_run_node],
                max_concurrent_activities=2,
                graceful_shutdown_timeout=timedelta(0),
            ):
                handle = await env.client.start_workflow(
                    TaskWorkflow.run,
                    args=[plan, str(uuid.uuid4())],
                    id=f"test-s4-heartbeat-recovery-{uuid.uuid4().hex}",
                    task_queue=TASK_QUEUE,
                )
                await asyncio.wait_for(first_attempt_started.wait(), timeout=5)
                await env.sleep(1)
                result: dict[str, Any] = await handle.result()

        assert result["status"] == "done"
        assert attempts == ["stalled", "recovered"]
        assert result["nodes"][0]["status"] == "done"

    asyncio.run(_run())
