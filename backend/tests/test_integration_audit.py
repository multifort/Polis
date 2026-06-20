"""集成测试（TD-011）：认证写操作落 audit_log（操作留痕）。"""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text


def _audit_actions_for(pg_url: str, actor: str) -> set[str]:
    engine = create_engine(pg_url.replace("+asyncpg", "+psycopg2"))
    try:
        with engine.connect() as conn:
            rows = conn.execute(text("SELECT action FROM audit_log WHERE actor = :a"), {"a": actor})
            return {r[0] for r in rows}
    finally:
        engine.dispose()


def test_register_login_audited(client: TestClient, pg_url: str) -> None:
    email = f"audit_{uuid.uuid4().hex[:8]}@polis.dev"

    r = client.post("/api/auth/register", json={"email": email, "password": "secret123"})
    assert r.status_code == 201
    auth = {"Authorization": f"Bearer {r.json()['access_token']}"}

    # 从 /api/me 拿到 user_id（审计 actor）
    me = client.get("/api/me", headers=auth)
    user_id = me.json()["user"]["id"]

    # 登录一次
    assert (
        client.post("/api/auth/login", json={"email": email, "password": "secret123"}).status_code
        == 200
    )

    actions = _audit_actions_for(pg_url, user_id)
    assert "auth.register" in actions, actions
    assert "auth.login" in actions, actions


def test_create_org_audited(client: TestClient, pg_url: str) -> None:
    email = f"audit_{uuid.uuid4().hex[:8]}@polis.dev"
    r = client.post("/api/auth/register", json={"email": email, "password": "secret123"})
    auth = {"Authorization": f"Bearer {r.json()['access_token']}"}
    user_id = client.get("/api/me", headers=auth).json()["user"]["id"]

    assert client.post("/api/orgs", json={"name": "审计公司"}, headers=auth).status_code == 201

    assert "org.create" in _audit_actions_for(pg_url, user_id)
