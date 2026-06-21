"""集成测试（M5-F / T5.7）：执行→写回→再检索闭环。

第一个 Agent 执行写回带出处事实；第二个 Agent 执行时检索到它并注入上下文。
"""

from __future__ import annotations

import asyncio
import uuid

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from polis.config import get_settings
from polis.modules.memory import repository as repo
from polis.modules.model.gateway import StubModelGateway
from polis.modules.runtime import agent_runtime
from polis.modules.runtime.guardrails import Guardrails
from polis.modules.runtime.mcp import default_registry
from polis.seed import seed


def _provision(client: TestClient) -> str:
    email = f"e2e_{uuid.uuid4().hex[:8]}@polis.dev"
    r = client.post("/api/auth/register", json={"email": email, "password": "secret123"})
    auth = {"Authorization": f"Bearer {r.json()['access_token']}"}
    pr = client.post(
        "/api/provision", json={"name": "采购记忆", "preset": "采购分析公司"}, headers=auth
    )
    assert pr.status_code == 201, pr.text
    return pr.json()["org"]["id"]


def test_second_agent_reads_first_agents_memory(client: TestClient, pg_url: str) -> None:
    asyncio.run(seed())
    org_id = _provision(client)

    async def _run() -> dict[str, object]:
        engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as s:
                # 节点1：询价Agent 执行 → 写回 role 记忆（带出处）
                await agent_runtime.execute(
                    s,
                    {
                        "id": "n1",
                        "type": "agent",
                        "required_capabilities": ["procurement.rfq"],
                        "input_hint": "供应商A交付准时率高",
                    },
                    org_id,
                    gateway=StubModelGateway(),
                    registry=default_registry(),
                    guard=Guardrails(),
                )
                # 节点2：分析Agent 执行 → ContextAssembler 检索到节点1 写回内容并注入
                res2 = await agent_runtime.execute(
                    s,
                    {
                        "id": "n2",
                        "type": "agent",
                        "required_capabilities": ["procurement.supplier_analysis"],
                        "input_hint": "供应商A交付",
                    },
                    org_id,
                    gateway=StubModelGateway(),  # 默认回显 user（含注入的记忆切片）
                    registry=default_registry(),
                    guard=Guardrails(),
                )
                # 校验：节点1 写回的事实带出处入库
                role_mems = await repo.list_by_scope(s, uuid.UUID(org_id), ["role"])
                contents = {m.content for m in role_mems}
                assert "[stub] 供应商A交付准时率高" in contents
                # 精确取节点1（询价Agent）写回那条，校验出处
                first = next(m for m in role_mems if m.content == "[stub] 供应商A交付准时率高")
                assert first.provenance and first.provenance.get("agent") == "询价Agent"
                return res2
        finally:
            await engine.dispose()

    res2 = asyncio.run(_run())
    # 第二个 Agent 的产出里带上了第一个 Agent 写入的记忆（经检索注入 → 桩回显）
    assert "供应商A交付准时率高" in str(res2["output"])
