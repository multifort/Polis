"""集成测试（V2-P1）：任务实体——可复用任务 + 执行记录关联（task_run.task_id）。"""

from __future__ import annotations

import asyncio
import uuid
from typing import TYPE_CHECKING, Any, cast

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from polis.config import get_settings
from polis.modules.planner import repository as repo
from polis.seed import seed

if TYPE_CHECKING:
    from fastapi.testclient import TestClient


def _auth(c: Any, email: str) -> dict[str, str]:
    r = c.post("/api/auth/register", json={"email": email, "password": "secret123"})
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_task_crud_and_run_link(client: TestClient) -> None:
    c = cast(Any, client)
    asyncio.run(seed())
    auth = _auth(c, f"task_{uuid.uuid4().hex[:8]}@polis.dev")
    org_id = c.post(
        "/api/provision", json={"name": "采购公司", "preset": "采购分析公司"}, headers=auth
    ).json()["org"]["id"]
    h = {**auth, "X-Org-Id": org_id}

    # ① 建任务（保存，不运行）
    r = c.post(
        "/api/tasks",
        json={"name": "供应商交付分析", "goal": "分析供应商交付", "priority": 7},
        headers=h,
    )
    assert r.status_code == 201, r.text
    task = r.json()
    assert task["name"] == "供应商交付分析" and task["goal"] == "分析供应商交付"
    assert task["priority"] == 7
    task_id = task["id"]

    # ② 列表含该任务
    lst = c.get("/api/tasks", headers=h).json()
    assert any(t["id"] == task_id and t["priority"] == 7 for t in lst)

    # ③ 执行记录初始为空
    runs = c.get(f"/api/tasks/{task_id}/runs", headers=h)
    assert runs.status_code == 200 and runs.json() == []

    # ④ 不存在任务 → 404
    assert c.get(f"/api/tasks/{uuid.uuid4()}/runs", headers=h).status_code == 404

    # ⑤ task_run.task_id 关联（直连 DB 验证，绕过 Temporal）
    async def _link() -> None:
        engine = create_async_engine(get_settings().database_url)
        try:
            async with async_sessionmaker(engine)() as s:
                oid = uuid.UUID(org_id)
                plan = await repo.create_plan(
                    s, org_id=oid, goal="g", dag={"nodes": []}, version="v1", estimated_cost_cents=1
                )
                run = await repo.create_task_run(
                    s, oid, plan.id, "wf-test", task_id=uuid.UUID(task_id)
                )
                await s.flush()
                assert run.task_id == uuid.UUID(task_id)
                linked = await repo.list_task_runs(s, oid, uuid.UUID(task_id))
                assert any(x[0].id == run.id for x in linked)
        finally:
            await engine.dispose()

    asyncio.run(_link())


def test_task_priority_derived_from_sla_inputs(client: TestClient) -> None:
    c = cast(Any, client)
    asyncio.run(seed())
    auth = _auth(c, f"task_sla_{uuid.uuid4().hex[:8]}@polis.dev")
    org_id = c.post(
        "/api/provision", json={"name": "采购公司", "preset": "采购分析公司"}, headers=auth
    ).json()["org"]["id"]
    h = {**auth, "X-Org-Id": org_id}

    derived = c.post(
        "/api/tasks",
        json={
            "name": "紧急供应商故障处理",
            "goal": "排查供应商交付故障",
            "inputs": {"sla": "urgent", "task_type": "customer"},
        },
        headers=h,
    )
    assert derived.status_code == 201, derived.text
    derived_task = derived.json()
    assert derived_task["priority"] == 90

    explicit_zero = c.post(
        "/api/tasks",
        json={
            "name": "手动降级任务",
            "goal": "保持低优先级处理",
            "priority": 0,
            "inputs": {"sla": "urgent", "task_type": "incident"},
        },
        headers=h,
    )
    assert explicit_zero.status_code == 201, explicit_zero.text
    zero_task = explicit_zero.json()
    assert zero_task["priority"] == 0

    lst = c.get("/api/tasks", headers=h).json()
    assert any(t["id"] == derived_task["id"] and t["priority"] == 90 for t in lst)
    assert any(t["id"] == zero_task["id"] and t["priority"] == 0 for t in lst)
