"""M3-C Temporal 编排：TaskWorkflow（串/并/human-gate/有界重规划）+ run_node 桩。

节点执行用确定性桩（M4 再接真实 Agent）。设计 03 §5/§6。
"""

from __future__ import annotations

import asyncio
import copy
from datetime import timedelta
from typing import Any

from temporalio import activity, workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError

with workflow.unsafe.imports_passed_through():
    from polis.modules.planner.schemas import PlanDag, PlanNode, validate

TASK_QUEUE = "polis-tasks"
MAX_REPLANS = 3
_ACTIVITY_TIMEOUT = timedelta(minutes=5)


# ── Activity ──────────────────────────────────────────────────────────────────


@activity.defn
async def run_node(node: dict[str, Any], org_id: str) -> dict[str, Any]:
    """桩执行器（M4 接真实 Agent）。

    fail_once=True：首次抛错触发 Temporal retry。
    fail_always=True：永远抛非重试错，用于测试有界重规划上限。
    """
    info = activity.info()
    node_id: str = node["id"]
    if node.get("fail_always"):
        raise ApplicationError(f"node {node_id} fail_always", non_retryable=True)
    if node.get("fail_once") and info.attempt == 1:
        raise ApplicationError(f"node {node_id} fail_once", non_retryable=False)
    return {
        "node_id": node_id,
        "ok": True,
        "agent": node.get("executor", "lite-agent"),
        "output": f"[stub] node {node_id} done",
    }


# ── 有界重规划 ─────────────────────────────────────────────────────────────────


def _bounded_replan(
    dag: PlanDag,
    failed_node_id: str,
    available_caps: set[str],
    replan_count: int,
) -> PlanDag:
    """移除失败节点并修复依赖引用，重新过 validate()。超 MAX_REPLANS 则抛 ApplicationError。"""
    if replan_count >= MAX_REPLANS:
        raise ApplicationError("超过最大重规划次数", non_retryable=True)
    new_nodes = [copy.deepcopy(n) for n in dag.nodes if n.id != failed_node_id]
    for n in new_nodes:
        n.deps = [d for d in n.deps if d != failed_node_id]
    patched = PlanDag(
        workflow_name=dag.workflow_name,
        goal=dag.goal,
        acceptance_criteria=dag.acceptance_criteria,
        budget_cents=dag.budget_cents,
        nodes=new_nodes,
    )
    vr = validate(patched, available_caps)
    if not vr.ok:
        raise ApplicationError(f"重规划后 DAG 不合法: {'; '.join(vr.errors)}", non_retryable=True)
    return patched


# ── Workflow ──────────────────────────────────────────────────────────────────


@workflow.defn
class TaskWorkflow:
    """按 PlanDag 拓扑+并行执行节点；human 节点挂起等 signal；有界重规划兜底（03 §5/§6）。"""

    def __init__(self) -> None:
        self._node_status: dict[str, str] = {}
        self._replan_count = 0
        self._approved_nodes: set[str] = set()
        # 原始 node dict（含 extra 字段如 fail_once/fail_always），传给 activity 用
        self._raw_nodes: dict[str, dict[str, Any]] = {}

    @workflow.run
    async def run(self, plan: dict[str, Any], org_id: str) -> dict[str, Any]:
        dag = PlanDag.model_validate(plan)
        # 保留原始 node dict（Pydantic model_dump 会丢掉 extra 字段）
        self._raw_nodes = {n["id"]: n for n in plan.get("nodes", [])}
        # 出图时已过 validate；此处从 DAG 自身推导可用能力集供重规划校验用
        available_caps: set[str] = {c for n in dag.nodes for c in n.required_capabilities}
        for n in dag.nodes:
            self._node_status[n.id] = "pending"

        abort = False
        while not abort:
            ready = [
                n
                for n in dag.nodes
                if self._node_status.get(n.id) not in ("done", "failed")
                and all(self._node_status.get(d) == "done" for d in n.deps)
            ]
            if not ready:
                break

            results: list[Any] = list(
                await asyncio.gather(
                    *[self._exec_node(n, org_id) for n in ready],
                    return_exceptions=True,
                )
            )

            for node, result in zip(ready, results, strict=False):
                if isinstance(result, BaseException):
                    try:
                        dag = _bounded_replan(dag, node.id, available_caps, self._replan_count)
                        self._replan_count += 1
                        self._node_status[node.id] = "failed"
                    except ApplicationError:
                        for n in dag.nodes:
                            if self._node_status.get(n.id) not in ("done",):
                                self._node_status[n.id] = "failed"
                        abort = True
                        break

        overall = "done" if all(s == "done" for s in self._node_status.values()) else "failed"
        return {
            "status": overall,
            "nodes": [{"id": k, "status": v} for k, v in self._node_status.items()],
        }

    @workflow.signal
    async def approve(self, node_id: str) -> None:
        """Human 节点审批信号。"""
        self._approved_nodes.add(node_id)

    @workflow.query
    def status(self) -> dict[str, Any]:
        """返回当前节点状态快照（供 GET /run 轮询）。"""
        return {"nodes": [{"id": k, "status": v} for k, v in self._node_status.items()]}

    async def _exec_node(self, node: PlanNode, org_id: str) -> dict[str, Any]:
        if node.type == "human":
            self._node_status[node.id] = "waiting_human"
            node_id = node.id

            def _is_approved() -> bool:
                return node_id in self._approved_nodes

            await workflow.wait_condition(_is_approved)
            self._node_status[node.id] = "done"
            return {"node_id": node.id, "ok": True}

        self._node_status[node.id] = "running"
        # 用原始 dict 传给 activity，保留 Pydantic 未定义的 extra 字段（如 fail_once/fail_always）
        raw_node = self._raw_nodes.get(node.id, node.model_dump())
        result: dict[str, Any] = await workflow.execute_activity(
            run_node,
            args=[raw_node, org_id],
            start_to_close_timeout=_ACTIVITY_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        self._node_status[node.id] = "done"
        return result
