"""集成测试（V2-S3 并发队列）：org 在跑数达上限 → pending 入队；count/cost 聚合正确。"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from polis.config import get_settings
from polis.modules.planner import repository as repo
from polis.modules.planner import workflow as planner_workflow
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
    task_id = c.post(
        "/api/tasks",
        json={"name": "t", "goal": "分析供应商交付", "priority": 9},
        headers=h,
    ).json()["id"]

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
                pending = [run for run, _ in rows if run.status == "pending"][0]
                assert pending.priority == 9
        finally:
            await engine.dispose()

    asyncio.run(_assert_queued())


def test_pending_run_auto_dequeue_starts_fifo(pg_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """S3 自动 dequeue：释放槽后最早 pending run 被切 running，并启动 Temporal workflow。"""
    engine = create_engine(pg_url.replace("+asyncpg", "+psycopg2"))
    try:
        with engine.begin() as conn:
            uid = conn.execute(
                text("INSERT INTO app_user (email) VALUES (:e) RETURNING id"),
                {"e": f"dq_{uuid.uuid4().hex[:8]}@polis.dev"},
            ).scalar()
            org_id = uuid.UUID(
                str(
                    conn.execute(
                        text(
                            "INSERT INTO org (name, owner_user_id) "
                            "VALUES ('队列公司', :u) RETURNING id"
                        ),
                        {"u": uid},
                    ).scalar()
                )
            )
    finally:
        engine.dispose()

    started: dict[str, Any] = {}

    class _Client:
        async def start_workflow(self, *_args: Any, **kwargs: Any) -> None:
            started["workflow_id"] = kwargs["id"]

    async def _connect(_addr: str) -> _Client:
        return _Client()

    monkeypatch.setattr("temporalio.client.Client.connect", _connect)

    async def _run() -> None:
        from polis.db.session import dispose_engine

        db = create_async_engine(get_settings().database_url)
        try:
            await dispose_engine()
            async with async_sessionmaker(db)() as s:
                plan = await repo.create_plan(
                    s,
                    org_id=org_id,
                    goal="queued",
                    dag={"workflow_name": "wf", "goal": "queued", "nodes": []},
                    version="generated",
                    estimated_cost_cents=100,
                )
                pending = await repo.create_task_run(
                    s,
                    org_id,
                    plan.id,
                    "queued",
                    status="pending",
                )
                pending_id = pending.id
                await s.commit()

            await planner_workflow._dequeue_pending_run(str(org_id))

            async with async_sessionmaker(db)() as s:
                run = await repo.get_task_run(s, org_id, pending_id)
                assert run is not None
                assert run.status == "running"
                assert run.started_at is not None
                assert run.temporal_workflow_id == started["workflow_id"]
                from polis.modules.observability import repository as obs_repo

                manifest = await obs_repo.get_run_manifest(s, org_id, pending_id)
                assert manifest is not None
        finally:
            await dispose_engine()
            await db.dispose()

    asyncio.run(_run())


def test_pending_run_auto_dequeue_fills_slots_by_priority(
    pg_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S3 多槽优先级队列：默认同 priority 时，短作业优先。"""
    engine = create_engine(pg_url.replace("+asyncpg", "+psycopg2"))
    try:
        with engine.begin() as conn:
            uid = conn.execute(
                text("INSERT INTO app_user (email) VALUES (:e) RETURNING id"),
                {"e": f"dq2_{uuid.uuid4().hex[:8]}@polis.dev"},
            ).scalar()
            org_id = uuid.UUID(
                str(
                    conn.execute(
                        text(
                            "INSERT INTO org (name, owner_user_id) "
                            "VALUES ('优先级队列公司', :u) RETURNING id"
                        ),
                        {"u": uid},
                    ).scalar()
                )
            )
    finally:
        engine.dispose()

    started: list[str] = []

    class _Client:
        async def start_workflow(self, *_args: Any, **kwargs: Any) -> None:
            started.append(kwargs["id"])

    async def _connect(_addr: str) -> _Client:
        return _Client()

    monkeypatch.setattr("temporalio.client.Client.connect", _connect)

    async def _run() -> None:
        from polis.db.session import dispose_engine

        db = create_async_engine(get_settings().database_url)
        pending_ids: dict[str, uuid.UUID] = {}
        try:
            await dispose_engine()
            async with async_sessionmaker(db)() as s:
                limit = get_settings().org_max_concurrent_runs
                for idx in range(max(limit - 2, 0)):
                    active_plan = await repo.create_plan(
                        s,
                        org_id=org_id,
                        goal=f"active-{idx}",
                        dag={"workflow_name": "wf", "goal": "active", "nodes": []},
                        version="generated",
                        estimated_cost_cents=999,
                    )
                    await repo.create_task_run(s, org_id, active_plan.id, f"active-{idx}")

                for label, cost in (("high", 300), ("low", 100), ("mid", 200)):
                    plan = await repo.create_plan(
                        s,
                        org_id=org_id,
                        goal=label,
                        dag={"workflow_name": "wf", "goal": label, "nodes": []},
                        version="generated",
                        estimated_cost_cents=cost,
                    )
                    run = await repo.create_task_run(
                        s,
                        org_id,
                        plan.id,
                        f"queued-{label}",
                        status="pending",
                    )
                    pending_ids[label] = run.id
                await s.commit()

            await planner_workflow._dequeue_pending_runs(str(org_id))

            async with async_sessionmaker(db)() as s:
                rows = {
                    label: await repo.get_task_run(s, org_id, run_id)
                    for label, run_id in pending_ids.items()
                }
                assert rows["low"] is not None and rows["low"].status == "running"
                assert rows["mid"] is not None and rows["mid"].status == "running"
                assert rows["high"] is not None and rows["high"].status == "pending"
                assert len(started) == 2
        finally:
            await dispose_engine()
            await db.dispose()

    asyncio.run(_run())


def test_next_pending_runs_tiebreaks_fifo(pg_url: str) -> None:
    """S3 队列排序：priority 和成本都相同时，按入队时间 FIFO。"""
    engine = create_engine(pg_url.replace("+asyncpg", "+psycopg2"))
    try:
        with engine.begin() as conn:
            uid = conn.execute(
                text("INSERT INTO app_user (email) VALUES (:e) RETURNING id"),
                {"e": f"dq_fifo_{uuid.uuid4().hex[:8]}@polis.dev"},
            ).scalar()
            org_id = uuid.UUID(
                str(
                    conn.execute(
                        text(
                            "INSERT INTO org (name, owner_user_id) "
                            "VALUES ('FIFO队列公司', :u) RETURNING id"
                        ),
                        {"u": uid},
                    ).scalar()
                )
            )
    finally:
        engine.dispose()

    async def _run() -> None:
        db = create_async_engine(get_settings().database_url)
        try:
            async with async_sessionmaker(db)() as s:
                base = datetime.now(UTC)
                run_ids: list[uuid.UUID] = []
                for label, offset in (("oldest", 0), ("middle", 1), ("newest", 2)):
                    plan = await repo.create_plan(
                        s,
                        org_id=org_id,
                        goal=label,
                        dag={"workflow_name": "wf", "goal": label, "nodes": []},
                        version="generated",
                        estimated_cost_cents=100,
                    )
                    run = await repo.create_task_run(
                        s,
                        org_id,
                        plan.id,
                        f"queued-{label}",
                        status="pending",
                        priority=3,
                    )
                    run_ids.append(run.id)
                    await s.execute(
                        text("UPDATE task_run SET created_at = :created_at WHERE id = :id"),
                        {"created_at": base + timedelta(seconds=offset), "id": run.id},
                    )
                await s.commit()

            async with async_sessionmaker(db)() as s:
                got = await repo.next_pending_runs(s, org_id, limit=3)
                assert [run.id for run in got] == run_ids
        finally:
            await db.dispose()

    asyncio.run(_run())


def test_next_pending_runs_large_batch_ordering(pg_url: str) -> None:
    """S3 队列压力回归：批量 pending 按 priority、成本、FIFO 精确排序。"""
    engine = create_engine(pg_url.replace("+asyncpg", "+psycopg2"))
    try:
        with engine.begin() as conn:
            uid = conn.execute(
                text("INSERT INTO app_user (email) VALUES (:e) RETURNING id"),
                {"e": f"dq_batch_{uuid.uuid4().hex[:8]}@polis.dev"},
            ).scalar()
            org_id = uuid.UUID(
                str(
                    conn.execute(
                        text(
                            "INSERT INTO org (name, owner_user_id) "
                            "VALUES ('批量队列公司', :u) RETURNING id"
                        ),
                        {"u": uid},
                    ).scalar()
                )
            )
    finally:
        engine.dispose()

    async def _run() -> None:
        db = create_async_engine(get_settings().database_url)
        try:
            async with async_sessionmaker(db)() as s:
                base = datetime.now(UTC)
                rows: list[tuple[int, int, datetime, uuid.UUID]] = []
                for idx in range(30):
                    priority = idx % 4
                    cost = [300, 100, 200, 100, 400][idx % 5]
                    created_at = base + timedelta(seconds=idx)
                    plan = await repo.create_plan(
                        s,
                        org_id=org_id,
                        goal=f"batch-{idx}",
                        dag={"workflow_name": "wf", "goal": f"batch-{idx}", "nodes": []},
                        version="generated",
                        estimated_cost_cents=cost,
                    )
                    run = await repo.create_task_run(
                        s,
                        org_id,
                        plan.id,
                        f"queued-batch-{idx}",
                        status="pending",
                        priority=priority,
                    )
                    await s.execute(
                        text("UPDATE task_run SET created_at = :created_at WHERE id = :id"),
                        {"created_at": created_at, "id": run.id},
                    )
                    rows.append((priority, cost, created_at, run.id))
                await s.commit()

            expected = [
                row_id
                for _priority, _cost, _created_at, row_id in sorted(
                    rows,
                    key=lambda row: (-row[0], row[1], row[2]),
                )[:12]
            ]
            async with async_sessionmaker(db)() as s:
                got = await repo.next_pending_runs(s, org_id, limit=12)
                assert [run.id for run in got] == expected
        finally:
            await db.dispose()

    asyncio.run(_run())


def test_pending_run_auto_dequeue_explicit_priority_over_cost(
    pg_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S3 生产级 priority：显式 priority 高的 pending run 优先于低成本 run。"""
    engine = create_engine(pg_url.replace("+asyncpg", "+psycopg2"))
    try:
        with engine.begin() as conn:
            uid = conn.execute(
                text("INSERT INTO app_user (email) VALUES (:e) RETURNING id"),
                {"e": f"dq3_{uuid.uuid4().hex[:8]}@polis.dev"},
            ).scalar()
            org_id = uuid.UUID(
                str(
                    conn.execute(
                        text(
                            "INSERT INTO org (name, owner_user_id) "
                            "VALUES ('显式优先级队列公司', :u) RETURNING id"
                        ),
                        {"u": uid},
                    ).scalar()
                )
            )
    finally:
        engine.dispose()

    started: list[str] = []

    class _Client:
        async def start_workflow(self, *_args: Any, **kwargs: Any) -> None:
            started.append(kwargs["id"])

    async def _connect(_addr: str) -> _Client:
        return _Client()

    monkeypatch.setattr("temporalio.client.Client.connect", _connect)

    async def _run() -> None:
        from polis.db.session import dispose_engine

        db = create_async_engine(get_settings().database_url)
        pending_ids: dict[str, uuid.UUID] = {}
        try:
            await dispose_engine()
            async with async_sessionmaker(db)() as s:
                limit = get_settings().org_max_concurrent_runs
                for idx in range(max(limit - 1, 0)):
                    active_plan = await repo.create_plan(
                        s,
                        org_id=org_id,
                        goal=f"active-{idx}",
                        dag={"workflow_name": "wf", "goal": "active", "nodes": []},
                        version="generated",
                        estimated_cost_cents=999,
                    )
                    await repo.create_task_run(s, org_id, active_plan.id, f"active-{idx}")

                for label, cost, priority in (
                    ("cheap", 10, 0),
                    ("urgent", 500, 10),
                ):
                    plan = await repo.create_plan(
                        s,
                        org_id=org_id,
                        goal=label,
                        dag={"workflow_name": "wf", "goal": label, "nodes": []},
                        version="generated",
                        estimated_cost_cents=cost,
                    )
                    run = await repo.create_task_run(
                        s,
                        org_id,
                        plan.id,
                        f"queued-{label}",
                        status="pending",
                        priority=priority,
                    )
                    pending_ids[label] = run.id
                await s.commit()

            await planner_workflow._dequeue_pending_runs(str(org_id))

            async with async_sessionmaker(db)() as s:
                rows = {
                    label: await repo.get_task_run(s, org_id, run_id)
                    for label, run_id in pending_ids.items()
                }
                assert rows["urgent"] is not None and rows["urgent"].status == "running"
                assert rows["cheap"] is not None and rows["cheap"].status == "pending"
                assert len(started) == 1
        finally:
            await dispose_engine()
            await db.dispose()

    asyncio.run(_run())
