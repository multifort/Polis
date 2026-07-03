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
REWORK_MAX = 1  # S2：单节点反馈重跑上限（§4.3 纠错预算）
_ACTIVITY_TIMEOUT = timedelta(minutes=5)
_QUALITY_TIMEOUT = timedelta(minutes=2)
# S4 长时运行：节点活动 heartbeat（worker 崩溃快速发现重试）
_HEARTBEAT_EVERY_S = 10
_HEARTBEAT_TIMEOUT = timedelta(seconds=40)


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

    # S4 长时运行：节点执行可达分钟级，后台周期 heartbeat → worker 崩溃可被 Temporal 快速发现重试
    # （配合 _run_node 的 heartbeat_timeout），而非死等 start_to_close_timeout。
    async def _heartbeat() -> None:
        while True:
            await asyncio.sleep(_HEARTBEAT_EVERY_S)
            activity.heartbeat()

    hb = asyncio.create_task(_heartbeat())
    try:
        return await execute_node(node, org_id, task_id or None, goal=goal or None)
    finally:
        hb.cancel()


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
    # 质量门用设计的 τ_pass（§4.3/§6/ADR-0012，缺省 0.6），而非 evaluator 通用默认 0.7——
    # 后者偏严，会把"本来够好、judge 有方差跌破 0.7"的产出误判（回炉：对齐设计阈值，降假阴性）。
    passed = r.assertions_ok and r.judge_score >= settings.quality_gate_tau
    return {"passed": passed, "judge": r.judge_score}


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

    # S3 自动 dequeue：当前 run 释放并发槽后，best-effort 启动最早 pending run。
    await _dequeue_pending_run(org_id)


async def _dequeue_pending_run(org_id: str) -> None:
    """S3 FIFO 自动 dequeue。失败不影响刚完成 run 的终态。"""
    import uuid

    from temporalio.client import Client

    from polis.config import get_settings
    from polis.db.session import get_sessionmaker, init_engine
    from polis.modules.observability import repository as obs_repo
    from polis.modules.planner import repository as repo

    try:
        settings = get_settings()
        init_engine()
        async with get_sessionmaker()() as session:
            org_uuid = uuid.UUID(org_id)
            if await repo.count_active_runs(session, org_uuid) >= settings.org_max_concurrent_runs:
                return
            run = await repo.next_pending_run(session, org_uuid)
            if run is None or run.plan_id is None:
                return
            plan = await repo.get_plan(session, org_uuid, run.plan_id)
            if plan is None:
                return

            workflow_id = f"plan-{plan.id}-{run.id}"
            client = await Client.connect(settings.temporal_addr)
            await client.start_workflow(
                TaskWorkflow.run,
                args=[plan.dag, org_id, str(run.id)],
                id=workflow_id,
                task_queue=TASK_QUEUE,
            )
            await repo.mark_task_run_running(session, run, workflow_id)
            await obs_repo.create_run_manifest(
                session,
                task_id=run.id,
                org_id=org_uuid,
                plan_snapshot=plan.dag,
                plan_version=plan.version,
                models_used={"chat": settings.default_chat_model},
                agents_used={},
            )
            await session.commit()
    except Exception:
        activity.logger.warning("S3 pending run 自动出队失败（不影响当前 run 终态）", exc_info=True)


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


@activity.defn
async def escalate_node(run_id: str, org_id: str, node_id: str, judge: float) -> None:
    """S2 ④ 升级人审：返工仍不达标 → 建一条 rework 审批进收件箱（超界交人，§4.2/§4.3）。"""
    import uuid

    from polis.db.session import get_sessionmaker, init_engine
    from polis.modules.observability import repository as obs_repo

    init_engine()
    async with get_sessionmaker()() as session:
        await obs_repo.create_approval(
            session,
            org_id=uuid.UUID(org_id),
            kind="rework",
            ref_id=run_id,
            payload={"node_id": node_id, "judge": judge, "reason": "返工后仍未达质量门，请复核"},
        )
        await session.commit()


@activity.defn
async def generate_replan_subdag(
    plan: dict[str, Any],
    failed_node_id: str,
    failure_reason: str,
    available_capabilities: list[str],
) -> list[dict[str, Any]]:
    """S2b ③ 在线局部重规划：调用 A2/A2b 内核生成 replacement nodes。

    workflow 只负责确定性拼接与状态推进；LLM 调用放在 Activity 内。
    """
    from polis.config import get_settings
    from polis.db.session import get_sessionmaker, init_engine
    from polis.modules.model.gateway import StubModelGateway, resolve_model
    from polis.modules.model.litellm_gateway import LiteLLMGateway
    from polis.modules.planner.generator import generate_subdag

    settings = get_settings()
    init_engine()
    async with get_sessionmaker()() as session:
        model = await resolve_model(session, settings.default_chat_model)
    gateway = LiteLLMGateway() if settings.deepseek_api_key else StubModelGateway()
    nodes = await generate_subdag(
        gateway,
        model,
        PlanDag.model_validate(plan),
        failed_node_id,
        failure_reason,
        set(available_capabilities),
    )
    return nodes


# ── 有界重规划 ─────────────────────────────────────────────────────────────────


def _affected_subgraph_ids(dag: PlanDag, failed_node_id: str) -> set[str]:
    """S2b：失败节点 + 依赖它的下游闭包，是局部重规划的最小影响范围。"""
    affected = {failed_node_id}
    changed = True
    while changed:
        changed = False
        for node in dag.nodes:
            if node.id in affected:
                continue
            if any(dep in affected for dep in node.deps):
                affected.add(node.id)
                changed = True
    return affected


def _local_replan(
    dag: PlanDag,
    failed_node_id: str,
    replacement_nodes: list[dict[str, Any]],
    available_caps: set[str],
    replan_count: int,
) -> tuple[PlanDag, set[str]]:
    """S2b 局部重规划：替换失败子图并重校验，返回 (新 DAG, 受影响节点 id)。

    这里的 replacement_nodes 是“回调内核重生成子图”的结果。生产路径后续可接 A2/A2b 内核；
    当前先把拼接与不变量守住，workflow 测试可用确定性子图覆盖控制面语义。
    """
    if replan_count >= MAX_REPLANS:
        raise ApplicationError("超过最大重规划次数", non_retryable=True)
    affected = _affected_subgraph_ids(dag, failed_node_id)
    replacements = [PlanNode.model_validate(n) for n in replacement_nodes]
    if not replacements:
        raise ApplicationError("局部重规划子图为空", non_retryable=True)
    replacement_ids = {n.id for n in replacements}
    kept = [copy.deepcopy(n) for n in dag.nodes if n.id not in affected]
    patched = PlanDag(
        workflow_name=dag.workflow_name,
        goal=dag.goal,
        acceptance_criteria=dag.acceptance_criteria,
        budget_cents=dag.budget_cents,
        nodes=[*kept, *replacements],
    )
    vr = validate(patched, available_caps)
    if not vr.ok:
        msg = f"局部重规划后 DAG 不合法: {'; '.join(vr.errors)}"
        raise ApplicationError(msg, non_retryable=True)
    return patched, affected | replacement_ids


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
        self._rework_count: dict[str, int] = {}  # S2：每节点反馈重跑次数

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
                        raw_node = self._raw_nodes.get(node.id, {})
                        if raw_node.get("local_replan_nodes"):
                            replacement_nodes = raw_node["local_replan_nodes"]
                        elif raw_node.get("local_replan") is True:
                            replacement_nodes = await workflow.execute_activity(
                                generate_replan_subdag,
                                args=[
                                    dag.model_dump(),
                                    node.id,
                                    str(result),
                                    sorted(available_caps),
                                ],
                                start_to_close_timeout=_QUALITY_TIMEOUT,
                                retry_policy=RetryPolicy(maximum_attempts=1),
                            )
                        else:
                            replacement_nodes = None

                        if replacement_nodes:
                            dag, affected = _local_replan(
                                dag,
                                node.id,
                                replacement_nodes,
                                available_caps,
                                self._replan_count,
                            )
                            replacement_ids = {
                                str(n.get("id")) for n in replacement_nodes if n.get("id")
                            }
                            for affected_id in affected:
                                if affected_id not in replacement_ids:
                                    self._node_status.pop(affected_id, None)
                                    self._raw_nodes.pop(affected_id, None)
                            for raw_replacement in replacement_nodes:
                                replacement_id = str(raw_replacement["id"])
                                self._raw_nodes[replacement_id] = raw_replacement
                                self._node_status[replacement_id] = "pending"
                        else:
                            dag = _bounded_replan(dag, node.id, available_caps, self._replan_count)
                            self._node_status[node.id] = "failed"
                        self._replan_count += 1
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
        result = await self._run_node(raw_node, org_id)

        # ── V2-S1 质量门 + S2 分级纠错（② rework → ④ escalate）──
        failed, judge = await self._assess(raw_node, result, reworked=False)
        self._quality[node.id] = judge
        if failed and self._rework_count.get(node.id, 0) < REWORK_MAX:
            # ② rework：把不达标原因喂回上下文，重跑【同节点】（上限 REWORK_MAX，§4.2）
            self._rework_count[node.id] = self._rework_count.get(node.id, 0) + 1
            self._node_status[node.id] = "replanning"
            fb = (raw_node.get("input_hint") or "") + (
                f"\n\n[返工反馈] 上次产出未达质量门(judge={judge:.2f})，请严格对照验收标准改进："
                f"{self._acceptance}"
            )
            result = await self._run_node({**raw_node, "input_hint": fb}, org_id)
            failed, judge = await self._assess(raw_node, result, reworked=True)
            self._quality[node.id] = judge
        if failed:
            # ④ escalate：返工仍不达标 → needs_rework + 升级人审（超界交人，§4.3）。
            # stub 为纯编排测试节点（无 DB），不建审批。
            self._node_status[node.id] = "needs_rework"
            if not raw_node.get("stub"):
                await workflow.execute_activity(
                    escalate_node,
                    args=[self._task_id, self._org_id, node.id, judge],
                    start_to_close_timeout=_QUALITY_TIMEOUT,
                    retry_policy=RetryPolicy(maximum_attempts=3),
                )
            return result

        self._node_status[node.id] = "done"
        return result

    async def _run_node(self, raw_node: dict[str, Any], org_id: str) -> dict[str, Any]:
        heartbeat_timeout = _HEARTBEAT_TIMEOUT
        if raw_node.get("heartbeat_timeout_ms") is not None:
            heartbeat_timeout = timedelta(milliseconds=int(raw_node["heartbeat_timeout_ms"]))
        result: dict[str, Any] = await workflow.execute_activity(
            run_node,
            args=[raw_node, org_id, self._task_id, self._goal],
            start_to_close_timeout=_ACTIVITY_TIMEOUT,
            heartbeat_timeout=heartbeat_timeout,  # S4：配合 run_node 后台 heartbeat
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        return result

    async def _assess(
        self, raw_node: dict[str, Any], result: dict[str, Any], *, reworked: bool
    ) -> tuple[bool, float]:
        """质量评估，返回 (是否不达标, judge)。含测试钩子 + 真实关键节点 Evaluator。"""
        if raw_node.get("rework_recover"):  # 测试钩子：首次不达标、返工即恢复
            return (not reworked, 1.0 if reworked else 0.0)
        if raw_node.get("force_rework"):
            return (True, 0.0)  # 测试钩子：强制不达标（返工仍失败 → 测 escalate 路径）
        if not raw_node.get("stub") and _is_key_node(raw_node) and self._acceptance:
            ev: dict[str, Any] = await workflow.execute_activity(
                evaluate_node,
                args=[str(result.get("output") or ""), self._acceptance],
                start_to_close_timeout=_QUALITY_TIMEOUT,
                retry_policy=RetryPolicy(maximum_attempts=2),
            )
            return (not ev.get("passed"), float(ev.get("judge") or 0.0))
        return (False, 1.0)  # 非关键/桩节点 → 视为达标
