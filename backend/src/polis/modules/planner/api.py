"""planner API 路由（M3-B/C）。

POST /api/plans                     → 出图（模板优先）
POST /api/plans/{id}/approve        → 审批并启动 Temporal 工作流
GET  /api/plans/{id}/run            → 查询运行状态（query workflow）
POST /api/plans/{id}/signal         → 审批 human 节点（signal workflow）
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from polis.config import get_settings
from polis.db.session import get_session
from polis.modules.observability import langfuse_client
from polis.modules.observability import repository as obs_repo
from polis.modules.observability.audit import write_audit
from polis.modules.org.deps import CurrentOrg, CurrentUserId, OrgContext, require_role
from polis.modules.planner import repository as repo
from polis.modules.planner import service
from polis.modules.planner.schemas import (
    ApproveResult,
    PlanCreateIn,
    PlanResult,
    RunNodeState,
    RunStatusResult,
    SignalIn,
    TaskCreateIn,
    TaskOut,
    TaskRunOut,
    derive_overall_status,
)
from polis.modules.planner.workflow import TASK_QUEUE, TaskWorkflow

router = APIRouter(prefix="/api", tags=["planner"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
# 审批/人审是治理动作：仅 owner/approver 可批准运行计划、放行人审 gate（09 §6 权限矩阵）
ApproverOrg = Annotated[OrgContext, Depends(require_role("owner", "approver"))]

_TEMPORAL_CONNECT_TIMEOUT = 5.0


async def _temporal_client() -> Any:
    """连接 Temporal；超时或不可达时抛 HTTPException 503。"""
    from temporalio.client import Client

    try:
        return await asyncio.wait_for(
            Client.connect(get_settings().temporal_addr),
            timeout=_TEMPORAL_CONNECT_TIMEOUT,
        )
    except Exception as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "编排服务未就绪") from exc


@router.post("/plans", response_model=PlanResult, status_code=status.HTTP_201_CREATED)
async def create_plan(data: PlanCreateIn, org: CurrentOrg, session: SessionDep) -> PlanResult:
    try:
        return await service.plan(session, org.org_id, data.goal)
    except service.NoTemplateMatch as exc:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "没有可用的计划模板（当前公司能力不足以匹配任何模板）"
        ) from exc
    except service.PlanInvalid as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail={"errors": exc.errors}
        ) from exc


async def _start_plan(
    session: AsyncSession,
    org_id: uuid.UUID,
    plan: Any,
    user_id: uuid.UUID,
    task_id: uuid.UUID | None = None,
) -> Any:
    """启动一个 plan 的 Temporal 工作流：建 task_run（贯通 task_id，TD-028）+ Run Manifest + 审计。

    approve_plan（直接出图后审批）与 run_task（任务驱动）共用。Temporal 不可达 → 503。
    """
    workflow_id = f"plan-{plan.id}"
    client = await _temporal_client()
    await repo.update_plan_status(session, org_id, plan.id, "running")
    run = await repo.create_task_run(session, org_id, plan.id, workflow_id, task_id=task_id)
    try:
        await client.start_workflow(
            TaskWorkflow.run,
            args=[plan.dag, str(org_id), str(run.id)],
            id=workflow_id,
            task_queue=TASK_QUEUE,
        )
    except Exception as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "编排服务未就绪") from exc

    dag_nodes = plan.dag.get("nodes", []) if isinstance(plan.dag, dict) else []
    await obs_repo.create_run_manifest(
        session,
        task_id=run.id,
        org_id=org_id,
        plan_snapshot=plan.dag,
        plan_version=plan.version,
        models_used={"chat": get_settings().default_chat_model},
        agents_used={
            n["id"]: n.get("required_capabilities", [])
            for n in dag_nodes
            if n.get("type") == "agent"
        },
    )
    await write_audit(
        session,
        action="plan.approve",
        actor=str(user_id),
        org_id=org_id,
        target=str(plan.id),
        detail={"task_id": str(run.id), "task": str(task_id) if task_id else None},
    )
    return run


@router.post(
    "/plans/{plan_id}/approve",
    response_model=ApproveResult,
    status_code=status.HTTP_201_CREATED,
)
async def approve_plan(
    plan_id: uuid.UUID, org: ApproverOrg, user_id: CurrentUserId, session: SessionDep
) -> ApproveResult:
    """审批计划并启动 Temporal TaskWorkflow（仅 owner/approver）。"""
    plan = await repo.get_plan(session, org.org_id, plan_id)
    if plan is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "计划不存在")
    if plan.status not in ("draft", "approved"):
        raise HTTPException(status.HTTP_409_CONFLICT, f"计划当前状态为 {plan.status!r}，无法启动")
    run = await _start_plan(session, org.org_id, plan, user_id)
    return ApproveResult(task_id=run.id, status="running")


# ── 任务实体（V2-P1）：可复用工作项 + 多次执行记录 ──────────────────────────────


@router.post("/tasks", response_model=TaskOut, status_code=status.HTTP_201_CREATED)
async def create_task(
    data: TaskCreateIn, org: CurrentOrg, user_id: CurrentUserId, session: SessionDep
) -> TaskOut:
    """新建一个可复用任务（保存，不立即运行）。"""
    task = await repo.create_task(
        session,
        org.org_id,
        name=data.name,
        goal=data.goal,
        scenario_ref=data.scenario_ref,
        input_schema=data.input_schema,
        inputs=data.inputs,
        created_by=user_id,
    )
    return TaskOut.model_validate(task, from_attributes=True)


@router.get("/tasks", response_model=list[TaskOut])
async def list_tasks(org: CurrentOrg, session: SessionDep) -> list[TaskOut]:
    rows = await repo.list_tasks(session, org.org_id)
    return [TaskOut.model_validate(t, from_attributes=True) for t in rows]


@router.get("/tasks/{task_id}/runs", response_model=list[TaskRunOut])
async def list_task_runs(
    task_id: uuid.UUID, org: CurrentOrg, session: SessionDep
) -> list[TaskRunOut]:
    """某任务的历次执行记录（1 任务:N 运行）。"""
    if await repo.get_task(session, org.org_id, task_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "任务不存在")
    rows = await repo.list_task_runs(session, org.org_id, task_id)
    return [TaskRunOut.model_validate(r, from_attributes=True) for r in rows]


@router.post(
    "/tasks/{task_id}/run", response_model=ApproveResult, status_code=status.HTTP_201_CREATED
)
async def run_task(
    task_id: uuid.UUID, org: ApproverOrg, user_id: CurrentUserId, session: SessionDep
) -> ApproveResult:
    """运行一个任务：出图（检索/生成）→ 快照 plan → 启动编排，记一条执行记录（owner/approver）。"""
    task = await repo.get_task(session, org.org_id, task_id)
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "任务不存在")
    try:
        plan_result = await service.plan(session, org.org_id, task.goal)
    except service.NoTemplateMatch as exc:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "没有可用的计划模板（当前公司能力不足以匹配任何模板）"
        ) from exc
    except service.PlanInvalid as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail={"errors": exc.errors}
        ) from exc
    plan = await repo.get_plan(session, org.org_id, plan_result.id)
    if plan is None:  # 理论不会（刚建）
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "计划快照丢失")
    run = await _start_plan(session, org.org_id, plan, user_id, task_id=task.id)
    return ApproveResult(task_id=run.id, status="running")


@router.get("/plans/{plan_id}/run", response_model=RunStatusResult)
async def get_plan_run(plan_id: uuid.UUID, org: CurrentOrg, session: SessionDep) -> RunStatusResult:
    """查询 Temporal 工作流当前节点状态。"""
    run = await repo.get_task_run_by_plan(session, org.org_id, plan_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "该计划尚未启动")

    client = await _temporal_client()

    try:
        handle = client.get_workflow_handle(run.temporal_workflow_id or "")
        raw: dict[str, Any] = await handle.query(TaskWorkflow.status)
    except Exception as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "编排服务未就绪") from exc

    nodes_raw: list[Any] = raw.get("nodes") or []
    nodes = [RunNodeState(id=str(n["id"]), status=str(n["status"])) for n in nodes_raw]
    # 顶层状态从节点派生（DB run.status 在 approve 后不会自动更新）
    overall = derive_overall_status([n.status for n in nodes])
    # 到达终态且 DB 仍为非终态时回写，保证 Temporal 保留期过后仍可读到正确状态
    _terminal = ("done", "failed", "needs_review")  # needs_review：质量门未过（V2-S1）
    if overall in _terminal and run.status not in _terminal:
        await repo.finish_task_run(session, run, overall)
    return RunStatusResult(status=overall, nodes=nodes)


@router.post("/plans/{plan_id}/signal", status_code=status.HTTP_204_NO_CONTENT)
async def signal_plan(
    plan_id: uuid.UUID,
    body: SignalIn,
    org: ApproverOrg,
    user_id: CurrentUserId,
    session: SessionDep,
) -> None:
    """向 human 节点发送审批 signal（仅 owner/approver）。"""
    run = await repo.get_task_run_by_plan(session, org.org_id, plan_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "该计划尚未启动")

    client = await _temporal_client()

    try:
        handle = client.get_workflow_handle(run.temporal_workflow_id or "")
        await handle.signal(TaskWorkflow.approve, body.node_id)
    except Exception as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "编排服务未就绪") from exc

    await write_audit(
        session,
        action="plan.signal",
        actor=str(user_id),
        org_id=org.org_id,
        target=str(plan_id),
        detail={"node_id": body.node_id},
    )


@router.get("/plans/{plan_id}/observability")
async def get_plan_observability(
    plan_id: uuid.UUID, org: CurrentOrg, session: SessionDep
) -> dict[str, Any]:
    """运行观测聚合（H-2）：任务状态 + manifest + 节点产出(出处) + LLM 调用明细(Langfuse)。"""
    run = await repo.get_task_run_by_plan(session, org.org_id, plan_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "该计划尚未启动")
    manifest = await obs_repo.get_run_manifest(session, org.org_id, run.id)
    envelopes = await obs_repo.get_envelopes_by_task(session, org.org_id, run.id)
    llm_calls = await langfuse_client.fetch_generations(str(run.id))
    await _fill_actual_cost(session, llm_calls)
    # started/finished_at 可能未回写（TD-019）→ 用节点产出时间兜底，保证「总耗时」可算。
    env_times = [e.created_at for e in envelopes if e.created_at is not None]
    started = run.started_at or run.created_at or (min(env_times) if env_times else None)
    finished = run.finished_at or (max(env_times) if env_times else None)
    duration = (finished - started).total_seconds() if started and finished else None
    return {
        "task_id": str(run.id),
        "status": run.status,
        "started_at": started.isoformat() if started is not None else None,
        "finished_at": finished.isoformat() if finished is not None else None,
        "duration_seconds": duration,
        "manifest": (
            {
                "plan_version": manifest.plan_version,
                "models_used": manifest.models_used,
                "agents_used": manifest.agents_used,
            }
            if manifest is not None
            else None
        ),
        "nodes": [
            {
                "node_id": e.node_id,
                "status": e.status,
                "summary": e.summary,
                "needs_human": e.needs_human,
                "created_at": e.created_at.isoformat() if e.created_at is not None else None,
                "provenance": (e.facts or {}).get("provenance") if e.facts else None,
            }
            for e in envelopes
        ],
        "llm_calls": llm_calls,
        **_aggregate_usage(llm_calls),
    }


async def _fill_actual_cost(session: AsyncSession, calls: list[dict[str, Any]]) -> None:
    """按 model_catalog 价格(元/1K token)算每次调用的**实际成本**(元)，覆盖 langfuse 的 cost。

    langfuse 对自研模型无定价表 → cost 恒为 null；用我们自己的目录价算，保证执行后展示实时费用。
    """
    from polis.modules.model.models import ModelCatalog

    rows = (await session.scalars(select(ModelCatalog))).all()
    prices = {r.id: (float(r.price_in or 0), float(r.price_out or 0)) for r in rows}
    for c in calls:
        pin, pout = prices.get(c.get("model") or "", (0.0, 0.0))
        it = c.get("input_tokens") or 0
        ot = c.get("output_tokens") or 0
        c["cost"] = round((it / 1000) * pin + (ot / 1000) * pout, 6)


def _aggregate_usage(calls: list[dict[str, Any]]) -> dict[str, Any]:
    """对标 Langfuse Dashboard：每次 LLM 调用聚合成总计 + 按模型分组（token/成本/次数）。"""
    totals: dict[str, Any] = {
        "calls": len(calls),
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "cost": 0.0,
    }
    by_model: dict[str, dict[str, Any]] = {}
    for c in calls:
        model = c.get("model") or "unknown"
        slot = by_model.setdefault(
            model,
            {
                "model": model,
                "calls": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
                "cost": 0.0,
            },
        )
        slot["calls"] += 1
        for key in ("input_tokens", "output_tokens", "total_tokens"):
            v = c.get(key) or 0
            slot[key] += v
            totals[key] += v
        cost = c.get("cost") or 0.0
        slot["cost"] += cost
        totals["cost"] += cost
    return {"totals": totals, "by_model": list(by_model.values())}


@router.get("/plans/{plan_id}/manifest")
async def get_plan_manifest(
    plan_id: uuid.UUID, org: CurrentOrg, session: SessionDep
) -> dict[str, Any]:
    """取任务运行的可复现快照（Run Manifest，T6.6）。"""
    run = await repo.get_task_run_by_plan(session, org.org_id, plan_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "该计划尚未启动")
    mf = await obs_repo.get_run_manifest(session, org.org_id, run.id)
    if mf is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "无运行快照")
    return {
        "task_id": str(mf.task_id),
        "started_at": mf.started_at.isoformat() if mf.started_at else None,
        "plan_version": mf.plan_version,
        "models_used": mf.models_used,
        "agents_used": mf.agents_used,
        "plan_snapshot": mf.plan_snapshot,
    }
