"""集成测试（M5-E）：memory 治理 API + org 行级隔离（A 不能读/删 B 的记忆）。"""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text


def _user_with_org(client: TestClient, pg_url: str) -> tuple[dict[str, str], str]:
    email = f"mapi_{uuid.uuid4().hex[:8]}@polis.dev"
    r = client.post("/api/auth/register", json={"email": email, "password": "secret123"})
    auth = {"Authorization": f"Bearer {r.json()['access_token']}"}
    org_id = client.post("/api/orgs", json={"name": "记忆治理"}, headers=auth).json()["id"]
    return auth, org_id


def _insert_memory(pg_url: str, org_id: str, content: str) -> str:
    engine = create_engine(pg_url.replace("+asyncpg", "+psycopg2"))
    try:
        with engine.begin() as conn:
            mid = conn.execute(
                text(
                    "INSERT INTO memory (org_id, scope, namespace, type, content) "
                    "VALUES (:o, 'org', 'procurement', 'factual', :c) RETURNING id"
                ),
                {"o": org_id, "c": content},
            ).scalar()
            return str(mid)
    finally:
        engine.dispose()


def test_memory_governance_and_isolation(client: TestClient, pg_url: str) -> None:
    auth_a, org_a = _user_with_org(client, pg_url)
    auth_b, org_b = _user_with_org(client, pg_url)
    mem_a = _insert_memory(pg_url, org_a, "A公司机密事实")

    ha = {**auth_a, "X-Org-Id": org_a}
    hb = {**auth_b, "X-Org-Id": org_b}

    # A 能浏览自己的记忆
    la = client.get("/api/orgs/current/memory", headers=ha)
    assert la.status_code == 200
    assert any(m["content"] == "A公司机密事实" for m in la.json())

    # B 浏览自己的（看不到 A 的）—— 行级隔离
    lb = client.get("/api/orgs/current/memory", headers=hb)
    assert lb.status_code == 200
    assert all(m["content"] != "A公司机密事实" for m in lb.json())

    # B 删 A 的记忆 → 404（org 隔离，不可见即不可删）
    assert client.delete(f"/api/memory/{mem_a}", headers=hb).status_code == 404

    # A（owner）删自己的 → 204
    assert client.delete(f"/api/memory/{mem_a}", headers=ha).status_code == 204
    # 删后不再可见
    la2 = client.get("/api/orgs/current/memory", headers=ha)
    assert all(m["content"] != "A公司机密事实" for m in la2.json())
