"""集成测试（V2-S3 并发队列）：org 在跑数达上限 → pending 入队；count/cost 聚合正确。"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any, cast

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from polis.config import get_settings
from polis.modules.planner import repository as repo
from polis.seed import seed


def _auth(c: Any, email: str) -> dict[str, str]:
    r = c.post("/api/auth/register", json={"email": email, "password": "secret123"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_concurrency_admission_queues_when_full(client: TestClient) -> None:
    c = cast(Any, client)
    asyncio.run(seed())
    auth = _auth(c, f"cc_{uuid.uuid4().hex[:8]}@polis.dev")
    org_id = c.post(
        "/api/provision", json={"name": "并发公司", "preset": "采购分析公司"}, headers=auth
    ).json()["org"]["id"]
    h = {**auth, "X-Org-Id": org_id}
    task_id = c.post("/api/tasks", json={"name": "t", "goal": "分析供应商交付"}, headers=h).json()[
        "id"
    ]

    limit = get_settings().org_max_concurrent_runs
    oid = uuid.UUID(org_id)

    # 直连 DB 灌满 limit 个 running run（不起真实 workflow），并验证聚合
    async def _fill() -> None:
        engine = create_async_engine(get_settings().database_url)
        try:
            async with async_sessionmaker(engine)() as s:
                for _ in range(limit):
                    plan = await repo.create_plan(
                        s,
                        org_id=oid,
                        goal="g",
                        dag={"nodes": []},
                        version="v1",
                        estimated_cost_cents=100,
                    )
                    await repo.create_task_run(s, oid, plan.id, "wf", task_id=uuid.UUID(task_id))
                await s.commit()
                assert await repo.count_active_runs(s, oid) == limit
                assert await repo.org_estimated_cost_cents(s, oid) == 100 * limit
        finally:
            await engine.dispose()

    asyncio.run(_fill())

    # 已达上限 → 不再 429，而是入队 pending（在连 Temporal 之前就返回）
    r = c.post(f"/api/tasks/{task_id}/run", headers=h)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "pending"

    async def _assert_queued() -> None:
        engine = create_async_engine(get_settings().database_url)
        try:
            async with async_sessionmaker(engine)() as s:
                rows = await repo.list_task_runs(s, oid, uuid.UUID(task_id))
                statuses = [run.status for run, _ in rows]
                assert statuses.count("running") == limit
                assert statuses.count("pending") == 1
        finally:
            await engine.dispose()

    asyncio.run(_assert_queued())
