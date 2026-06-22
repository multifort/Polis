"""集成测试 T8.3：多租户隔离回归（API 层 A/B 互不可见）。

补 test_integration_rls.py（DB/RLS 层）之上的**应用层**隔离：
两个真实用户各开一家公司，断言跨租户访问被 CurrentOrg 成员校验拦截、各自只见自己的花名册。
"""

from __future__ import annotations

import asyncio
import uuid
from typing import TYPE_CHECKING, Any, cast

from polis.seed import seed

if TYPE_CHECKING:
    from fastapi.testclient import TestClient


def _register(client: Any, email: str) -> dict[str, str]:
    r = client.post("/api/auth/register", json={"email": email, "password": "secret123"})
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _provision(client: Any, auth: dict[str, str], name: str) -> str:
    r = client.post(
        "/api/provision",
        json={"name": name, "preset": "采购分析公司"},
        headers=auth,
    )
    assert r.status_code == 201, r.text
    return str(r.json()["org"]["id"])


def test_tenant_isolation_api(client: TestClient) -> None:
    c = cast(Any, client)
    asyncio.run(seed())  # 预设 + 计划模板入库
    suffix = uuid.uuid4().hex[:8]

    auth_a = _register(c, f"tenant_a_{suffix}@polis.dev")
    auth_b = _register(c, f"tenant_b_{suffix}@polis.dev")
    org_a = _provision(c, auth_a, "A 采购公司")
    org_b = _provision(c, auth_b, "B 采购公司")
    assert org_a != org_b

    ha = {**auth_a, "X-Org-Id": org_a}
    hb = {**auth_b, "X-Org-Id": org_b}

    # ① 各自只见自己的花名册，且两边 Agent id 不相交（org 隔离实例化）
    agents_a = c.get("/api/orgs/current/agents", headers=ha)
    agents_b = c.get("/api/orgs/current/agents", headers=hb)
    assert agents_a.status_code == 200 and agents_b.status_code == 200
    ids_a = {a["id"] for a in agents_a.json()}
    ids_b = {a["id"] for a in agents_b.json()}
    assert ids_a and ids_b
    assert ids_a.isdisjoint(ids_b)

    # ② 跨租户访问被成员校验拦截：B 用 A 的 org_id → 403
    r = c.get("/api/orgs/current/agents", headers={**auth_b, "X-Org-Id": org_a})
    assert r.status_code == 403, r.text
    r = c.get("/api/orgs/current/agents", headers={**auth_a, "X-Org-Id": org_b})
    assert r.status_code == 403, r.text

    # ③ A 在自己公司出图；B 看不到该计划（org 作用域查询落空 → 404，非 200）
    plan = c.post("/api/plans", json={"goal": "分析供应商交付"}, headers=ha)
    assert plan.status_code == 201, plan.text
    plan_id = plan.json()["id"]
    # B 拿 A 的 plan_id + 自己的 org 上下文：查不到（不会把 A 的运行数据泄露给 B）
    r = c.get(f"/api/plans/{plan_id}/observability", headers=hb)
    assert r.status_code == 404, r.text
    r = c.get(f"/api/plans/{plan_id}/manifest", headers=hb)
    assert r.status_code == 404, r.text

    # ④ 缺 X-Org-Id 头 → 400（fail-closed，不默认任何公司）
    r = c.get("/api/orgs/current/agents", headers=auth_a)
    assert r.status_code == 400, r.text
