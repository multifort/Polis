"""集成测试（M6 H-2 / TD-028）：execute 写 envelope 关联 task_id + 观测聚合按任务取节点。"""

from __future__ import annotations

import asyncio
import json
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from polis.config import get_settings
from polis.modules.model.gateway import StubModelGateway
from polis.modules.observability import repository as obs_repo
from polis.modules.runtime import agent_runtime
from polis.modules.runtime.guardrails import Guardrails
from polis.modules.runtime.mcp import default_registry
from polis.seed import seed


def _register(client: TestClient) -> dict[str, str]:
    email = f"obs_{uuid.uuid4().hex[:8]}@polis.dev"
    r = client.post("/api/auth/register", json={"email": email, "password": "secret123"})
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _provision(client: TestClient) -> str:
    auth = _register(client)
    return client.post(
        "/api/provision", json={"name": "观测公司", "preset": "采购分析公司"}, headers=auth
    ).json()["org"]["id"]


def _make_plan_task_run(pg_url: str, org_id: str) -> tuple[str, str]:
    """造一个 plan + task_run，返回 plan.id / task_run.id。"""
    engine = create_engine(pg_url.replace("+asyncpg", "+psycopg2"))
    try:
        with engine.begin() as conn:
            pid = conn.execute(
                text(
                    "INSERT INTO plan (org_id, goal, dag, version) "
                    "VALUES (:o, 'g', '{}', 'v1') RETURNING id"
                ),
                {"o": org_id},
            ).scalar()
            rid = conn.execute(
                text(
                    "INSERT INTO task_run (org_id, plan_id, temporal_workflow_id, status) "
                    "VALUES (:o, :p, 'wf', 'running') RETURNING id"
                ),
                {"o": org_id, "p": pid},
            ).scalar()
            return str(pid), str(rid)
    finally:
        engine.dispose()


def _make_task_run(pg_url: str, org_id: str) -> str:
    """造一个 plan + task_run，返回 task_run.id（envelope.task_id 需 FK 到它）。"""
    _, run_id = _make_plan_task_run(pg_url, org_id)
    return run_id


def _insert_envelope_with_guardrails(pg_url: str, org_id: str, task_id: str) -> None:
    engine = create_engine(pg_url.replace("+asyncpg", "+psycopg2"))
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO result_envelope "
                    "(org_id, task_id, node_id, status, summary, content, facts) "
                    "VALUES (:o, :t, 'n1', 'done', '摘要', '已脱敏输出', CAST(:facts AS jsonb))"
                ),
                {
                    "o": org_id,
                    "t": task_id,
                    "facts": json.dumps(
                        {
                            "guardrails": {
                                "changed": True,
                                "redactions": {"pii_or_secret": 2, "injection": 1},
                            },
                            "provenance": {"agent": "采购分析员"},
                        }
                    ),
                },
            )
    finally:
        engine.dispose()


def test_execute_links_task_id_and_aggregates(client: TestClient, pg_url: str) -> None:
    asyncio.run(seed())
    org_id = _provision(client)
    task_id = _make_task_run(pg_url, org_id)

    node = {
        "id": "n1",
        "type": "agent",
        "required_capabilities": ["procurement.rfq"],
        "input_hint": "询价",
    }

    async def _run() -> list[object]:
        engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as s:
                await agent_runtime.execute(
                    s,
                    node,
                    org_id,
                    task_id=task_id,  # TD-028：贯通 task_run.id
                    gateway=StubModelGateway(),
                    registry=default_registry(),
                    guard=Guardrails(),
                )
                await s.commit()
                # 观测聚合：按 task_id 取节点产出
                envs = await obs_repo.get_envelopes_by_task(
                    s, uuid.UUID(org_id), uuid.UUID(task_id)
                )
                return list(envs)
        finally:
            await engine.dispose()

    envs = asyncio.run(_run())
    assert len(envs) == 1
    assert str(envs[0].task_id) == task_id  # envelope 关联到 task_run
    assert envs[0].node_id == "n1"
    assert envs[0].status == "done"


def test_observability_exposes_guardrail_redaction_audit(client: TestClient, pg_url: str) -> None:
    asyncio.run(seed())
    auth = _register(client)
    org_id = client.post(
        "/api/provision", json={"name": "观测审计公司", "preset": "采购分析公司"}, headers=auth
    ).json()["org"]["id"]
    plan_id, task_id = _make_plan_task_run(pg_url, org_id)
    _insert_envelope_with_guardrails(pg_url, org_id, task_id)

    r = client.get(
        f"/api/plans/{plan_id}/observability",
        headers={**auth, "X-Org-Id": org_id},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["guardrails"] == {
        "changed": True,
        "redactions": {"pii_or_secret": 2, "injection": 1},
    }
    assert data["nodes"][0]["guardrails"]["changed"] is True
    assert data["nodes"][0]["guardrails"]["redactions"]["pii_or_secret"] == 2
    assert data["nodes"][0]["provenance"]["agent"] == "采购分析员"
