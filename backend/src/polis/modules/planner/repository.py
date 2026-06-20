"""planner 数据访问层。集中 SQL，service 只调这里（12 C 分层）。"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from polis.modules.org.models import Agent, AgentCapability
from polis.modules.planner.models import Plan, PlanTemplate, TaskRun


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


async def get_plan(session: AsyncSession, plan_id: uuid.UUID) -> Plan | None:
    """按 ID 取计划（RLS 已在会话级限定 org）。"""
    plan: Plan | None = await session.scalar(select(Plan).where(Plan.id == plan_id))
    return plan


async def update_plan_status(session: AsyncSession, plan_id: uuid.UUID, new_status: str) -> None:
    plan = await get_plan(session, plan_id)
    if plan is not None:
        plan.status = new_status
        await session.flush()


async def create_task_run(
    session: AsyncSession,
    org_id: uuid.UUID,
    plan_id: uuid.UUID,
    temporal_workflow_id: str,
) -> TaskRun:
    run = TaskRun(
        org_id=org_id,
        plan_id=plan_id,
        temporal_workflow_id=temporal_workflow_id,
        status="running",
    )
    session.add(run)
    await session.flush()
    return run


async def get_task_run_by_plan(session: AsyncSession, plan_id: uuid.UUID) -> TaskRun | None:
    run: TaskRun | None = await session.scalar(
        select(TaskRun).where(TaskRun.plan_id == plan_id).order_by(TaskRun.created_at.desc())
    )
    return run
