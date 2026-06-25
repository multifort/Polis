"""planner 数据访问层。集中 SQL，service 只调这里（12 C 分层）。"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from polis.db.org_scoped import select_org_scoped
from polis.modules.org.models import Agent, AgentCapability
from polis.modules.planner.models import Plan, PlanTemplate, Task, TaskRun


async def available_capabilities(session: AsyncSession) -> set[str]:
    """当前公司（RLS 限定）所有 active Agent 的能力并集。"""
    rows = await session.execute(
        select(AgentCapability.capability)
        .join(Agent, Agent.id == AgentCapability.agent_id)
        .where(Agent.status == "active")
    )
    return {c for (c,) in rows.all()}


async def list_plan_templates(session: AsyncSession) -> list[PlanTemplate]:
    """全局计划模板（无 org_id），按 name/version 稳定排序。"""
    return list(
        (
            await session.scalars(
                select(PlanTemplate).order_by(PlanTemplate.name, PlanTemplate.version)
            )
        ).all()
    )


async def create_plan(
    session: AsyncSession,
    org_id: uuid.UUID,
    goal: str,
    dag: dict[str, Any],
    version: str | None,
    estimated_cost_cents: int,
) -> Plan:
    plan = Plan(
        org_id=org_id,
        goal=goal,
        dag=dag,
        version=version,
        status="draft",
        estimated_cost_cents=estimated_cost_cents,
    )
    session.add(plan)
    await session.flush()
    return plan


async def get_plan(session: AsyncSession, org_id: uuid.UUID, plan_id: uuid.UUID) -> Plan | None:
    """按 ID 取计划。RLS 已限定 org，叠加应用层 org_id 过滤做纵深防御（TD-015）。"""
    plan: Plan | None = await session.scalar(
        select_org_scoped(Plan, org_id).where(Plan.id == plan_id)
    )
    return plan


async def update_plan_status(
    session: AsyncSession, org_id: uuid.UUID, plan_id: uuid.UUID, new_status: str
) -> None:
    plan = await get_plan(session, org_id, plan_id)
    if plan is not None:
        plan.status = new_status
        await session.flush()


async def create_task_run(
    session: AsyncSession,
    org_id: uuid.UUID,
    plan_id: uuid.UUID,
    temporal_workflow_id: str,
    task_id: uuid.UUID | None = None,
) -> TaskRun:
    run = TaskRun(
        org_id=org_id,
        task_id=task_id,  # V2-P1：关联可复用任务（nullable，兼容直接出图的旧/临时运行）
        plan_id=plan_id,
        temporal_workflow_id=temporal_workflow_id,
        status="running",
    )
    session.add(run)
    await session.flush()
    return run


# ── 任务实体（V2-P1）──────────────────────────────────────────────────────────


async def create_task(
    session: AsyncSession,
    org_id: uuid.UUID,
    *,
    name: str,
    goal: str,
    scenario_ref: str | None = None,
    input_schema: dict[str, Any] | None = None,
    inputs: dict[str, Any] | None = None,
    created_by: uuid.UUID | None = None,
) -> Task:
    task = Task(
        org_id=org_id,
        name=name,
        goal=goal,
        scenario_ref=scenario_ref,
        input_schema=input_schema,
        inputs=inputs,
        created_by=created_by,
    )
    session.add(task)
    await session.flush()
    return task


async def list_tasks(session: AsyncSession, org_id: uuid.UUID) -> list[Task]:
    q = select_org_scoped(Task, org_id).order_by(Task.created_at.desc())
    return list((await session.scalars(q)).all())


async def get_task(session: AsyncSession, org_id: uuid.UUID, task_id: uuid.UUID) -> Task | None:
    t: Task | None = await session.scalar(select_org_scoped(Task, org_id).where(Task.id == task_id))
    return t


async def list_task_runs(
    session: AsyncSession, org_id: uuid.UUID, task_id: uuid.UUID
) -> list[TaskRun]:
    q = (
        select_org_scoped(TaskRun, org_id)
        .where(TaskRun.task_id == task_id)
        .order_by(TaskRun.created_at.desc())
    )
    return list((await session.scalars(q)).all())


async def get_task_run(
    session: AsyncSession, org_id: uuid.UUID, run_id: uuid.UUID
) -> TaskRun | None:
    run: TaskRun | None = await session.scalar(
        select_org_scoped(TaskRun, org_id).where(TaskRun.id == run_id)
    )
    return run


async def get_task_run_by_plan(
    session: AsyncSession, org_id: uuid.UUID, plan_id: uuid.UUID
) -> TaskRun | None:
    run: TaskRun | None = await session.scalar(
        select_org_scoped(TaskRun, org_id)
        .where(TaskRun.plan_id == plan_id)
        .order_by(TaskRun.created_at.desc())
    )
    return run


async def finish_task_run(session: AsyncSession, run: TaskRun, new_status: str) -> None:
    """工作流到达终态时回写 task_run + 关联 plan 的状态（保持 DB 与编排一致）。"""
    run.status = new_status
    run.finished_at = datetime.now(UTC)
    if run.plan_id is not None:
        # done/needs_review 原样回写（plan CHECK 已含），其余归 failed
        plan_status = new_status if new_status in ("done", "needs_review") else "failed"
        await update_plan_status(session, run.org_id, run.plan_id, plan_status)
    await session.flush()
