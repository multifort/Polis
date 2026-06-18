"""集成测试（批次A）：当前公司中间件 + 运行时 RLS（HTTP 层）+ 成员/头校验。"""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text


def _register(client: TestClient) -> dict[str, str]:
    email = f"ctx_{uuid.uuid4().hex[:8]}@polis.dev"
    r = client.post("/api/auth/register", json={"email": email, "password": "secret123"})
    assert r.status_code == 201
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_org_context_runtime_rls(client: TestClient, pg_url: str) -> None:
    auth = _register(client)
    org_a = client.post("/api/orgs", json={"name": "甲公司"}, headers=auth).json()["id"]
    org_b = client.post("/api/orgs", json={"name": "乙公司"}, headers=auth).json()["id"]

    # 造 role 行（provisioning 在批次B；此处直接以 superuser 插入）
    engine = create_engine(pg_url.replace("+asyncpg", "+psycopg2"))
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO role (org_id, name) VALUES (:o, '甲-角色')"), {"o": org_a})
        conn.execute(text("INSERT INTO role (org_id, name) VALUES (:o, '乙-角色')"), {"o": org_b})
    engine.dispose()

    # X-Org-Id=A → 只见 A 的角色（运行时 RLS 生效）
    ra = client.get("/api/orgs/current/roles", headers={**auth, "X-Org-Id": org_a})
    assert ra.status_code == 200
    assert [r["name"] for r in ra.json()] == ["甲-角色"]

    # 切到 B → 只见 B
    rb = client.get("/api/orgs/current/roles", headers={**auth, "X-Org-Id": org_b})
    assert [r["name"] for r in rb.json()] == ["乙-角色"]

    # 非成员公司 → 403
    rx = client.get("/api/orgs/current/roles", headers={**auth, "X-Org-Id": str(uuid.uuid4())})
    assert rx.status_code == 403

    # 缺 X-Org-Id → 400
    assert client.get("/api/orgs/current/roles", headers=auth).status_code == 400
