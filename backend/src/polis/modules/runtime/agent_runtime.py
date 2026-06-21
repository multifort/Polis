"""AgentRuntime：单节点执行入口（design 04 §1/§7）。

组装上下文 → lite-agent 循环 → ResultEnvelope(出处) 入库 → 记忆写回 → 调用日志 → NodeResult。
请求外执行（Temporal Activity），无 RLS 上下文，故用 select_org_scoped 显式 org 过滤（TD-015）。
M4 用桩模型/记忆/凭证（ADR-0007）。
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from polis.db.org_scoped import select_org_scoped
from polis.db.session import get_sessionmaker, init_engine
from polis.modules.memory import center as memory_center
from polis.modules.memory.models import ResultEnvelope
from polis.modules.model.gateway import ModelGateway, StubModelGateway
from polis.modules.org.models import Agent, AgentCapability, AgentVersion
from polis.modules.org.schemas import AgentConfig
from polis.modules.runtime import context
from polis.modules.runtime.agent import run_loop
from polis.modules.runtime.guardrails import Guardrails
from polis.modules.runtime.mcp import McpRegistry, McpRuntime, default_registry
from polis.modules.runtime.models import SkillInvocation


async def _select_agent_scoped(
    session: AsyncSession, org_id: uuid.UUID, caps: list[str]
) -> Agent | None:
    """org 显式过滤选一个能力匹配的 active Agent（请求外，不依赖 RLS）。"""
    q = select_org_scoped(Agent, org_id).where(Agent.status == "active")
    if caps:
        q = q.join(AgentCapability, AgentCapability.agent_id == Agent.id).where(
            AgentCapability.capability.in_(caps)
        )
    agent: Agent | None = await session.scalar(q.limit(1))
    return agent


async def _load_config(session: AsyncSession, org_id: uuid.UUID, agent: Agent) -> AgentConfig:
    av = await session.scalar(
        select_org_scoped(AgentVersion, org_id).where(AgentVersion.agent_id == agent.id)
    )
    if av is None:
        return AgentConfig(prompt=agent.name)
    return AgentConfig.model_validate(av.config)


async def execute(
    session: AsyncSession,
    node: dict[str, Any],
    org_id: str,
    *,
    gateway: ModelGateway,
    registry: McpRegistry,
    guard: Guardrails | None,
) -> dict[str, Any]:
    """执行单节点：选 Agent → 组装 → 循环 → 出处入库 → 记忆写回 → 调用日志。"""
    org_uuid = uuid.UUID(org_id)
    caps = node.get("required_capabilities") or []
    agent = await _select_agent_scoped(session, org_uuid, caps)
    config = (
        await _load_config(session, org_uuid, agent)
        if agent is not None
        else AgentConfig(prompt=node.get("input_hint") or "执行节点")
    )
    task_id = str(node.get("id") or "node")

    ctx = await context.build(session, config, node, org_uuid, task_id)
    loop = await run_loop(gateway, McpRuntime(registry), config.prompt, ctx, guard=guard)

    status = "done" if loop.ok else ("blocked" if loop.blocked else "failed")
    envelope = ResultEnvelope(
        org_id=org_uuid,
        node_id=str(node.get("id") or ""),
        agent_id=(agent.id if agent is not None else None),
        status=status,
        summary=loop.content,
        facts={
            "output": loop.content,
            "tool_outputs": loop.tool_outputs,
            "provenance": {
                "agent": (agent.name if agent is not None else None),
                "executor": config.executor,
                "stub_model": True,  # ADR-0007：桩模型产出，非真实 LLM
            },
        },
        needs_human=loop.blocked,
    )
    session.add(envelope)
    await session.flush()

    # 调用日志（聚合一条，计费/可观测字段；T4.6）
    session.add(
        SkillInvocation(
            org_id=org_uuid,
            agent_id=(agent.id if agent is not None else None),
            skill_id=None,
            latency_ms=0,
            cost_cents=0,
            status=status,
        )
    )
    # 记忆写回（成功且有内容；M4 桩直写，M5 换写管线）
    if loop.ok and loop.content:
        await memory_center.write_fact(
            session,
            org_uuid,
            f"org:{org_id}",
            loop.content,
            {"node_id": node.get("id"), "agent": (agent.name if agent is not None else None)},
        )
    await session.flush()

    return {
        "node_id": node.get("id"),
        "ok": loop.ok,
        "agent": (agent.name if agent is not None else None),
        "output": loop.content,
        "envelope_id": str(envelope.id),
        "needs_human": loop.blocked,
        "replannable": loop.soft_fail,
    }


async def execute_node(node: dict[str, Any], org_id: str) -> dict[str, Any]:
    """Temporal Activity 入口：自建 session + 默认桩依赖执行单节点。"""
    init_engine()
    async with get_sessionmaker()() as session:
        result = await execute(
            session,
            node,
            org_id,
            gateway=StubModelGateway(),
            registry=default_registry(),
            guard=Guardrails(),
        )
        await session.commit()
        return result
