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

    workflow_id = f"plan-{plan_id}"
    client = await _temporal_client()

    # 先建 task_run 拿 id，贯通到 workflow→节点执行（TD-028）
    await repo.update_plan_status(session, org.org_id, plan_id, "running")
    run = await repo.create_task_run(session, org.org_id, plan_id, workflow_id)

    try:
        await client.start_workflow(
            TaskWorkflow.run,
            args=[plan.dag, str(org.org_id), str(run.id)],
            id=workflow_id,
            task_queue=TASK_QUEUE,
        )
    except Exception as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "编排服务未就绪") from exc

    # Run Manifest：落可复现快照（plan 快照 + 模型 + agent 能力需求）—— T6.6
    dag_nodes = plan.dag.get("nodes", []) if isinstance(plan.dag, dict) else []
    await obs_repo.create_run_manifest(
        session,
        task_id=run.id,
        org_id=org.org_id,
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
        org_id=org.org_id,
        target=str(plan_id),
        detail={"task_id": str(run.id)},
    )
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
    if overall in ("done", "failed") and run.status not in ("done", "failed"):
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
    return {
        "task_id": str(run.id),
        "status": run.status,
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
                "provenance": (e.facts or {}).get("provenance") if e.facts else None,
            }
            for e in envelopes
        ],
        "llm_calls": llm_calls,
    }


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
