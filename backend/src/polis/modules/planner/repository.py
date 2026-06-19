"""planner 数据访问层。集中 SQL，service 只调这里（12 C 分层）。"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from polis.modules.org.models import Agent, AgentCapability
from polis.modules.planner.models import Plan, PlanTemplate


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
