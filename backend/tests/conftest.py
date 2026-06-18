"""集成测试 fixture（TD-007）：起临时 pgvector 容器 + 跑迁移 + 提供 TestClient。

Docker 不可用时整体跳过，绝不阻塞 pre-push。
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

# 禁用 testcontainers reaper（ryuk），避免离线时拉镜像失败
os.environ.setdefault("TESTCONTAINERS_RYUK_DISABLED", "true")

# macOS Docker Desktop 的 socket 不在默认 /var/run/docker.sock，未设 DOCKER_HOST 时自动探测
if not os.environ.get("DOCKER_HOST"):
    _sock = os.path.expanduser("~/.docker/run/docker.sock")
    if os.path.exists(_sock):
        os.environ["DOCKER_HOST"] = f"unix://{_sock}"

PG_IMAGE = "pgvector/pgvector:pg18"


@pytest.fixture(scope="session")
def pg_url() -> Iterator[str]:
    """启动临时 pgvector 容器，跑 alembic 到 head，导出 asyncpg 连接串。"""
    try:
        from testcontainers.postgres import PostgresContainer
    except ImportError as exc:  # pragma: no cover
        pytest.skip(f"testcontainers 不可用：{exc}")

    try:
        pg = PostgresContainer(PG_IMAGE, username="polis", password="polis", dbname="polis")
        pg.start()
    except Exception as exc:  # noqa: BLE001 - Docker 不可用即跳过整组集成测试
        pytest.skip(f"Docker 不可用，跳过集成测试：{exc}")

    try:
        host = pg.get_container_host_ip()
        port = pg.get_exposed_port(5432)
        url = f"postgresql+asyncpg://polis:polis@{host}:{port}/polis"
        os.environ["POLIS_DATABASE_URL"] = url

        from polis.config import get_settings

        get_settings.cache_clear()

        from alembic import command
        from alembic.config import Config

        command.upgrade(Config("alembic.ini"), "head")
        yield url
    finally:
        pg.stop()


@pytest.fixture
def client(pg_url: str) -> Iterator[object]:
    """对临时库运行的 FastAPI TestClient（context manager 触发 lifespan）。"""
    from fastapi.testclient import TestClient

    from polis.main import app

    with TestClient(app) as c:
        yield c
