"""集成测试（M6-B）：配置凭证 API（信封加密入库）+ scoped 取 owner Key + 跨用户隔离。"""

from __future__ import annotations

import asyncio
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from polis.config import get_settings
from polis.modules.model import credential
from polis.seed import seed


def _register_with_org(client: TestClient) -> tuple[dict[str, str], str]:
    email = f"cred_{uuid.uuid4().hex[:8]}@polis.dev"
    r = client.post("/api/auth/register", json={"email": email, "password": "secret123"})
    auth = {"Authorization": f"Bearer {r.json()['access_token']}"}
    org_id = client.post("/api/orgs", json={"name": "凭证公司"}, headers=auth).json()["id"]
    return auth, org_id


def test_configure_credential_envelope_and_scoped(client: TestClient, pg_url: str) -> None:
    asyncio.run(seed())  # 需要 model_catalog 有 deepseek-v4-pro
    auth, org_id = _register_with_org(client)
    h = {**auth, "X-Org-Id": org_id}

    # owner 配置 DeepSeek Key
    r = client.post(
        "/api/credentials",
        json={"model_id": "deepseek-v4-pro", "api_key": "sk-test-deepseek-key"},
        headers=h,
    )
    assert r.status_code == 201, r.text
    assert r.json() == {"model_id": "deepseek-v4-pro", "configured": True}

    # 入库为密文（不含明文）
    engine = create_engine(pg_url.replace("+asyncpg", "+psycopg2"))
    try:
        with engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT ciphertext, dek_wrapped FROM credential "
                    "WHERE model_id = 'deepseek-v4-pro'"
                )
            ).first()
            assert row is not None
            assert b"sk-test-deepseek-key" not in bytes(row[0])
    finally:
        engine.dispose()

    # scoped 取 owner Key（信封解密）
    async def _scoped() -> credential.ScopedCredential:
        eng = create_async_engine(get_settings().database_url, pool_pre_ping=True)
        try:
            async with async_sessionmaker(eng, expire_on_commit=False)() as s:
                return await credential.scoped(s, uuid.UUID(org_id), "deepseek-v4-pro", "task1")
        finally:
            await eng.dispose()

    sc = asyncio.run(_scoped())
    assert sc.value == "sk-test-deepseek-key"


def test_unknown_model_rejected(client: TestClient) -> None:
    asyncio.run(seed())
    auth, org_id = _register_with_org(client)
    r = client.post(
        "/api/credentials",
        json={"model_id": "no-such-model", "api_key": "sk-x"},
        headers={**auth, "X-Org-Id": org_id},
    )
    assert r.status_code == 404


def test_scoped_without_credential_returns_no_value(client: TestClient) -> None:
    asyncio.run(seed())
    auth, org_id = _register_with_org(client)

    async def _scoped() -> credential.ScopedCredential:
        eng = create_async_engine(get_settings().database_url, pool_pre_ping=True)
        try:
            async with async_sessionmaker(eng, expire_on_commit=False)() as s:
                return await credential.scoped(s, uuid.UUID(org_id), "deepseek-v4-pro", "t")
        finally:
            await eng.dispose()

    sc = asyncio.run(_scoped())
    assert sc.value is None  # 未配置 → 无明文（由 gateway env 兜底）
