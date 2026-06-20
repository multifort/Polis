"""集成测试（TD-012）：登出吊销 / refresh 轮换 / 会话清理。"""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient


def _register(client: TestClient) -> dict[str, str]:
    email = f"life_{uuid.uuid4().hex[:8]}@polis.dev"
    r = client.post("/api/auth/register", json={"email": email, "password": "secret123"})
    assert r.status_code == 201
    return {"email": email, **r.json()}


def test_logout_revokes_refresh(client: TestClient) -> None:
    tok = _register(client)
    # 登出吊销 refresh
    out = client.post("/api/auth/logout", json={"refresh_token": tok["refresh_token"]})
    assert out.status_code == 204
    # 吊销后再 refresh 应 401
    r = client.post("/api/auth/refresh", json={"refresh_token": tok["refresh_token"]})
    assert r.status_code == 401


def test_logout_is_idempotent(client: TestClient) -> None:
    tok = _register(client)
    # 重复登出仍 204（幂等，不泄露存在性）
    for _ in range(2):
        assert (
            client.post(
                "/api/auth/logout", json={"refresh_token": tok["refresh_token"]}
            ).status_code
            == 204
        )


def test_refresh_rotation(client: TestClient) -> None:
    tok = _register(client)
    old = tok["refresh_token"]

    # 用旧 refresh 换新一对
    r1 = client.post("/api/auth/refresh", json={"refresh_token": old})
    assert r1.status_code == 200
    new = r1.json()["refresh_token"]
    assert new != old, "refresh 应轮换为新值"

    # 旧 refresh 已失效（轮换吊销）
    assert client.post("/api/auth/refresh", json={"refresh_token": old}).status_code == 401
    # 新 refresh 可用
    assert client.post("/api/auth/refresh", json={"refresh_token": new}).status_code == 200


def test_cleanup_removes_revoked(client: TestClient) -> None:
    import asyncio

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from polis.config import get_settings
    from polis.modules.org import repository as repo

    tok = _register(client)
    client.post("/api/auth/logout", json={"refresh_token": tok["refresh_token"]})

    # 用独立 engine（当前 loop）跑清理，避免复用 app engine 的跨事件循环冲突
    async def _cleanup() -> int:
        engine = create_async_engine(get_settings().database_url)
        try:
            async with async_sessionmaker(engine)() as s:
                n = await repo.cleanup_auth_sessions(s)
                await s.commit()
                return n
        finally:
            await engine.dispose()

    assert asyncio.run(_cleanup()) >= 1
