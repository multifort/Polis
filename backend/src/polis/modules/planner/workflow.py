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
    # 显式 pass through pydantic（含 C 扩展 pydantic_core），否则沙箱在首个 workflow task
    # 内延迟加载 pydantic_core 会触发 "imported after initial workflow load" UserWarning（TD-018）。
    import pydantic  # noqa: F401
    import pydantic_core  # noqa: F401

    from polis.modules.planner.schemas import PlanDag, PlanNode, derive_overall_status, validate

TASK_QUEUE = "polis-tasks"
MAX_REPLANS = 3
_ACTIVITY_TIMEOUT = timedelta(minutes=5)
_QUALITY_TIMEOUT = timedelta(minutes=2)


def _is_key_node(node: dict[str, Any]) -> bool:
    """关键节点（V2-S1 质量门只评关键节点）：显式 evaluate=True，或能力含 report/generation。"""
    if node.get("evaluate") is True:
        return True
    caps = node.get("required_capabilities") or []
    return any(("report" in c or "generation" in c) for c in caps)


# ── Activity ──────────────────────────────────────────────────────────────────


@activity.defn
async def run_node(
    node: dict[str, Any], org_id: str, task_id: str = "", goal: str = ""
) -> dict[str, Any]:
    """节点执行 Activity。

    - fail_once=True：首次抛错触发 Temporal retry（编排测试用）。
    - fail_always=True：永远抛非重试错，测有界重规划上限（编排测试用）。
    - stub=True：返回桩结果，不连 DB（纯编排测试用，见 test_workflow）。
    - 否则：调真实 AgentRuntime.execute_node（M4-F，经 Agent+工具+桩模型执行 + 出处入库）。
    task_id 为 task_run.id（贯通到 envelope/调用日志/trace 便于观测按任务聚合，TD-028）。
    """
    info = activity.info()
    node_id: str = node["id"]
    if node.get("fail_always"):
        raise ApplicationError(f"node {node_id} fail_always", non_retryable=True)
    if node.get("fail_once") and info.attempt == 1:
        raise ApplicationError(f"node {node_id} fail_once", non_retryable=False)
    if node.get("stub"):
        return {
            "node_id": node_id,
            "ok": True,
            "agent": node.get("executor", "lite-agent"),
            "output": f"[stub] node {node_id} done",
        }
    from polis.modules.runtime.agent_runtime import execute_node

    return await execute_node(node, org_id, task_id or None, goal=goal or None)


@activity.defn
async def evaluate_node(output: str, acceptance_criteria: str) -> dict[str, Any]:
    """质量门 Activity（V2-S1）：对关键节点产出做 Evaluator 评分（断言 + LLM-judge）。

    无验收标准/空产出 → 视为通过；有 Key 用真实 LiteLLM judge，否则确定性桩。返回 {passed, judge}。
    """
    if not acceptance_criteria or not output:
        return {"passed": True, "judge": 1.0}

    from polis.config import get_settings
    from polis.db.session import get_sessionmaker, init_engine
    from polis.modules.model.gateway import StubModelGateway, resolve_model
    from polis.modules.model.litellm_gateway import LiteLLMGateway
    from polis.modules.observability import evaluator

    settings = get_settings()
    init_engine()
    async with get_sessionmaker()() as session:
        model = await resolve_model(session, settings.default_chat_model)
    gateway = LiteLLMGateway() if settings.deepseek_api_key else StubModelGateway()
    r = await evaluator.score(gateway, model, output, acceptance_criteria=acceptance_criteria)
    return {"passed": r.passed, "judge": r.judge_score}


@activity.defn
async def finalize_run(run_id: str, org_id: str, overall: str) -> None:
    """终态回写 Activity：工作流跑完后把 task_run/plan 写成终态。

    回写不再依赖客户端轮询 GET /run（任务页只读 DB/产出，从不轮询 → 旧实现会让状态卡在
    running，见 TD-031）。由工作流自身在结束时驱动，保证 DB 与编排一致。幂等：已是终态则跳过。
    """
    import uuid

    from polis.db.session import get_sessionmaker, init_engine
    from polis.modules.planner import repository as repo

    _terminal = ("done", "failed", "needs_review")
    init_engine()
    async with get_sessionmaker()() as session:
        run = await repo.get_task_run(session, uuid.UUID(org_id), uuid.UUID(run_id))
        if run is not None and run.status not in _terminal:
            await repo.finish_task_run(session, run, overall)
            await session.commit()

    # V2-B3 自动晋升：任务成功完成 → 蒸馏产出为公司知识（org 记忆）。best-effort，失败不影响终态。
    if overall == "done":
        await _promote_task_memory(org_id, run_id)


async def _promote_task_memory(org_id: str, run_id: str) -> None:
    """读本任务产出 → 蒸馏 → 晋升到 org 记忆（飞轮）。独立会话、独立 try，绝不影响 run 终态。"""
    import uuid

    from polis.config import get_settings
    from polis.db.session import get_sessionmaker
    from polis.modules.memory import center as memory_center
    from polis.modules.model.gateway import StubModelGateway, resolve_model
    from polis.modules.model.litellm_gateway import LiteLLMGateway

    try:
        settings = get_settings()
        gateway = LiteLLMGateway() if settings.deepseek_api_key else StubModelGateway()
        async with get_sessionmaker()() as session:
            model = await resolve_model(session, settings.default_chat_model)
            await memory_center.promote_facts_from_task(
                session, gateway, model, uuid.UUID(org_id), uuid.UUID(run_id)
            )
            await session.commit()
    except Exception:
        activity.logger.warning("promote_facts_from_task 失败（不影响 run 终态）", exc_info=True)


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
        self._task_id = ""  # task_run.id（TD-028，贯通到节点执行）
        self._org_id = ""  # 终态回写用（TD-031）
        self._goal = ""  # 用户意图（F3：贯通到 Agent 上下文，让产出锚定目标）
        self._acceptance = ""  # 验收标准（V2-S1 质量门）
        self._quality: dict[str, float] = {}  # 关键节点 judge 分数（观测用）

    @workflow.run
    async def run(self, plan: dict[str, Any], org_id: str, task_id: str = "") -> dict[str, Any]:
        self._task_id = task_id
        self._org_id = org_id
        dag = PlanDag.model_validate(plan)
        self._goal = str(plan.get("goal") or dag.goal or "")
        self._acceptance = str(dag.acceptance_criteria or "")
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
                # needs_rework 在 S1 不再调度（S2 接自动纠错）；done/failed 终态不重跑
                if self._node_status.get(n.id) not in ("done", "failed", "needs_rework")
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

        overall = derive_overall_status(list(self._node_status.values()))
        # 终态回写 DB（不依赖任何客户端轮询，TD-031）。task_id 为空＝纯编排桩测，跳过 DB。
        if self._task_id and self._org_id:
            await workflow.execute_activity(
                finalize_run,
                args=[self._task_id, self._org_id, overall],
                start_to_close_timeout=_QUALITY_TIMEOUT,
                retry_policy=RetryPolicy(maximum_attempts=5),
            )
        return {
            "status": overall,
            "nodes": [{"id": k, "status": v} for k, v in self._node_status.items()],
            "quality": self._quality,
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
            args=[raw_node, org_id, self._task_id, self._goal],
            start_to_close_timeout=_ACTIVITY_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        # ── V2-S1 关键节点质量门 ──
        if raw_node.get("force_rework"):  # 测试钩子：强制不达标
            self._node_status[node.id] = "needs_rework"
            self._quality[node.id] = 0.0
            return result
        if not raw_node.get("stub") and _is_key_node(raw_node) and self._acceptance:
            ev: dict[str, Any] = await workflow.execute_activity(
                evaluate_node,
                args=[str(result.get("output") or ""), self._acceptance],
                start_to_close_timeout=_QUALITY_TIMEOUT,
                retry_policy=RetryPolicy(maximum_attempts=2),
            )
            self._quality[node.id] = float(ev.get("judge") or 0.0)
            if not ev.get("passed"):
                # 不达标 → needs_rework（S1 不再调度；S2 接自动纠错/局部重规划）
                self._node_status[node.id] = "needs_rework"
                return result

        self._node_status[node.id] = "done"
        return result
