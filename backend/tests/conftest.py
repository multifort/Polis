"""集成测试 fixture（TD-007）：起临时 pgvector 容器 + 跑迁移 + 提供 TestClient。

Docker 不可用时整体跳过，绝不阻塞 pre-push。
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

# 禁用 testcontainers reaper（ryuk），避免离线时拉镜像失败
os.environ.setdefault("TESTCONTAINERS_RYUK_DISABLED", "true")

# macOS Docker Desktop 的 socket 不在默认 /var/run/docker.sock，未设 DOCKER_HOST 时自动探测
if not os.environ.get("DOCKER_HOST"):
    _sock = os.path.expanduser("~/.docker/run/docker.sock")
    if os.path.exists(_sock):
        os.environ["DOCKER_HOST"] = f"unix://{_sock}"

PG_IMAGE = "pgvector/pgvector:pg18"


def pytest_configure(config: pytest.Config) -> None:
    """Use an explicitly provisioned Temporal test server when configured.

    The SDK still owns process startup, time skipping and shutdown.  This only
    supplies its public ``test_server_existing_path`` argument so environments
    with a blocked SDK downloader can run the same tests without skipping them.
    """
    del config
    configured_path = os.environ.get("POLIS_TEMPORAL_TEST_SERVER_PATH")
    if not configured_path:
        return

    server_path = Path(configured_path).expanduser().resolve()
    if not server_path.is_file() or not os.access(server_path, os.X_OK):
        raise RuntimeError(
            f"POLIS_TEMPORAL_TEST_SERVER_PATH must point to an executable file: {server_path}"
        )

    from temporalio.testing import WorkflowEnvironment

    original = WorkflowEnvironment.start_time_skipping.__func__

    async def start_time_skipping_with_existing_server(
        cls: type[WorkflowEnvironment], **kwargs: Any
    ) -> WorkflowEnvironment:
        kwargs.setdefault("test_server_existing_path", str(server_path))
        return await original(cls, **kwargs)

    WorkflowEnvironment.start_time_skipping = classmethod(  # type: ignore[method-assign]
        start_time_skipping_with_existing_server
    )


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
    from polis.modules.org import auth_rate_limit

    auth_rate_limit.reset_for_tests()
    with TestClient(app) as c:
        yield c
    auth_rate_limit.reset_for_tests()
