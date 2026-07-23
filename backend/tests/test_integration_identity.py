"""集成测试（TD-007）：对真实 pgvector 库跑身份/组织全流程 + schema/RLS 断言。"""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text


def _email() -> str:
    # 用真实 TLD：.test/.example 等是 RFC 保留特殊域名，会被 EmailStr 拒收
    return f"it_{uuid.uuid4().hex[:10]}@polis.dev"


def test_ready(client: TestClient) -> None:
    resp = client.get("/ready")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "db": "up"}


def test_cors_allows_cookie_credentials_for_local_frontend(client: TestClient) -> None:
    resp = client.options(
        "/api/me",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert resp.status_code == 200
    assert resp.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert resp.headers["access-control-allow-credentials"] == "true"


def test_register_login_me_create_org(client: TestClient) -> None:
    email = _email()

    # 注册 → 拿到 token
    r = client.post(
        "/api/auth/register", json={"email": email, "password": "secret123", "display_name": "测试"}
    )
    assert r.status_code == 201
    access = r.json()["access_token"]
    auth = {"Authorization": f"Bearer {access}"}

    # /me：刚注册无公司
    r = client.get("/api/me", headers=auth)
    assert r.status_code == 200
    body = r.json()
    assert body["user"]["email"] == email
    assert body["orgs"] == []

    # 建公司 → owner
    r = client.post("/api/orgs", json={"name": "采购分析公司"}, headers=auth)
    assert r.status_code == 201
    assert r.json()["role"] == "owner"

    # /me：公司出现
    r = client.get("/api/me", headers=auth)
    orgs = r.json()["orgs"]
    assert len(orgs) == 1
    assert orgs[0]["name"] == "采购分析公司"

    # 登录（新 token）
    r = client.post("/api/auth/login", json={"email": email, "password": "secret123"})
    assert r.status_code == 200
    assert "access_token" in r.json()


def test_auth_cookie_can_call_me_without_bearer(client: TestClient) -> None:
    email = _email()
    r = client.post("/api/auth/register", json={"email": email, "password": "secret123"})
    assert r.status_code == 201
    assert "polis_access" in client.cookies
    assert "polis_refresh" in client.cookies

    r = client.get("/api/me")
    assert r.status_code == 200
    assert r.json()["user"]["email"] == email


def test_auth_failures(client: TestClient) -> None:
    email = _email()
    client.post("/api/auth/register", json={"email": email, "password": "secret123"})

    assert (
        client.post("/api/auth/login", json={"email": email, "password": "wrong"}).status_code
        == 401
    )
    assert (
        client.post(
            "/api/auth/register", json={"email": email, "password": "secret123"}
        ).status_code
        == 409
    )
    client.cookies.clear()
    assert client.get("/api/me").status_code == 401  # 无令牌


def test_login_failures_are_rate_limited(client: TestClient) -> None:
    email = _email()
    client.post("/api/auth/register", json={"email": email, "password": "secret123"})

    for _ in range(4):
        r = client.post("/api/auth/login", json={"email": email, "password": "wrong"})
        assert r.status_code == 401

    r = client.post("/api/auth/login", json={"email": email, "password": "wrong"})
    assert r.status_code == 429
    assert int(r.headers["Retry-After"]) > 0

    r = client.post("/api/auth/login", json={"email": email, "password": "secret123"})
    assert r.status_code == 429


def test_schema_and_rls(pg_url: str) -> None:
    engine = create_engine(pg_url.replace("+asyncpg", "+psycopg2"))
    try:
        with engine.connect() as conn:
            tables = conn.execute(
                text(
                    "SELECT count(*) FROM information_schema.tables "
                    "WHERE table_schema='public' AND table_type='BASE TABLE'"
                )
            ).scalar_one()
            rls = conn.execute(
                text("SELECT count(*) FROM pg_class WHERE relrowsecurity AND relkind='r'")
            ).scalar_one()
        assert tables >= 27  # 27 业务表 + alembic_version（+ V2 新增 task 等）
        # 原 15 张 + V3 K1 的 3 张 Definition 资产表和 3 张 Bundle 表。
        assert rls == 21
    finally:
        engine.dispose()
