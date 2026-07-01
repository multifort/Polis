"""集成测试（V2-P4）：跨任务/场景运营统计看板聚合。

直接建 plan/task_run/approval（绕过 Temporal），断言 /api/dashboard 的
状态分布/成功率/复用命中率/人审通过率/场景分布 计算正确。
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from polis.config import get_settings
from polis.modules.observability import repository as obs_repo
from polis.modules.planner import repository as planner_repo
from polis.seed import seed


def _register(c: Any, email: str) -> dict[str, str]:
    r = c.post("/api/auth/register", json={"email": email, "password": "secret123"})
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _provision(c: Any, auth: dict[str, str], name: str) -> str:
    r = c.post("/api/provision", json={"name": name, "preset": "采购分析公司"}, headers=auth)
    assert r.status_code == 201, r.text
    return str(r.json()["org"]["id"])


def _seed_dashboard_data(org_id: uuid.UUID, user_id: uuid.UUID) -> None:
    """建 4 条 task_run（2 模板命中 done、1 生成 failed、1 模板命中 needs_review）
    + 2 条已决 approval。
    """

    async def _run() -> None:
        engine = create_async_engine(get_settings().database_url)
        try:
            async with async_sessionmaker(engine)() as s:
                now = datetime.now(UTC)

                async def _mk(version: str | None, status: str, dur_s: int) -> None:
                    plan = await planner_repo.create_plan(
                        s,
                        org_id,
                        goal="g",
                        dag={"nodes": []},
                        version=version,
                        estimated_cost_cents=100,
                    )
                    wf_id = f"wf-{uuid.uuid4().hex[:6]}"
                    run = await planner_repo.create_task_run(s, org_id, plan.id, wf_id)
                    run.status = status
                    run.started_at = now - timedelta(seconds=dur_s)
                    run.finished_at = now
                    await s.flush()

                await _mk("supplier_v1", "done", 10)
                await _mk("supplier_v1", "done", 20)
                await _mk(None, "failed", 5)
                await _mk("supplier_v1", "needs_review", 15)

                ap1 = await obs_repo.create_approval(
                    s, org_id=org_id, kind="plan", ref_id="x", payload={}
                )
                ap2 = await obs_repo.create_approval(
                    s, org_id=org_id, kind="plan", ref_id="y", payload={}
                )
                await obs_repo.decide_approval(s, ap1, approve=True, decided_by=user_id)
                await obs_repo.decide_approval(s, ap2, approve=False, decided_by=user_id)
                await s.commit()
        finally:
            await engine.dispose()

    asyncio.run(_run())


def test_dashboard_aggregation(client: Any) -> None:
    c = cast(Any, client)
    asyncio.run(seed())
    auth = _register(c, f"dash_{uuid.uuid4().hex[:8]}@polis.dev")
    org_id = _provision(c, auth, "看板验证公司")
    h = {**auth, "X-Org-Id": org_id}
    me = c.get("/api/me", headers=auth)
    user_id = me.json()["user"]["id"]

    _seed_dashboard_data(uuid.UUID(org_id), uuid.UUID(user_id))

    r = c.get("/api/dashboard", headers=h)
    assert r.status_code == 200, r.text
    d = r.json()

    assert d["total_runs"] == 4
    assert d["by_status"]["done"] == 2
    assert d["by_status"]["failed"] == 1
    assert d["by_status"]["needs_review"] == 1
    # 成功率 = done / 全部终态(done+failed+needs_review) = 2/4
    assert abs(d["success_rate"] - 0.5) < 1e-9
    # 复用命中率：3 条 version 非空 / 4 条总数
    assert abs(d["reuse_hit_rate"] - 0.75) < 1e-9
    # 人审通过率：1 approved / 2 已决
    assert abs(d["approval_pass_rate"] - 0.5) < 1e-9
    # 场景分布含 supplier_v1(3) + generated(1)
    templates = {t["template"]: t["count"] for t in d["by_template"]}
    assert templates["supplier_v1"] == 3
    assert templates["generated"] == 1
    assert d["avg_duration_seconds"] is not None and d["avg_duration_seconds"] > 0
    assert d["active_runs"] == 0
    assert d["org_max_concurrent_runs"] > 0


def test_dashboard_empty_org(client: Any) -> None:
    """无任何运行的公司：聚合字段优雅返回 None/0，不报错。"""
    c = cast(Any, client)
    asyncio.run(seed())
    auth = _register(c, f"dash2_{uuid.uuid4().hex[:8]}@polis.dev")
    org_id = _provision(c, auth, "空看板公司")
    h = {**auth, "X-Org-Id": org_id}

    r = c.get("/api/dashboard", headers=h)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["total_runs"] == 0
    assert d["success_rate"] is None
    assert d["reuse_hit_rate"] is None
    assert d["approval_pass_rate"] is None
    assert d["by_template"] == []
