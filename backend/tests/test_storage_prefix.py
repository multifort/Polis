"""T7.6 对象存储：key 前缀构造 + 多租户隔离。

- 单测（无网络）：`object_key` 前缀构造与路径穿越校验；
- 集成测（testcontainers MinIO，Docker 不可用则跳过）：put/get/presigned/delete 通，
  且 org A 无法读到 org B 前缀下的对象（前缀隔离）。
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import Iterator

import pytest

from polis.modules.storage import ObjectStore, StorageError, StorageKeyError, object_key

# ---------- 单测：key 构造与穿越校验（无网络，恒运行） ----------


def test_object_key_basic() -> None:
    assert object_key("orgA", "task1", "report.md") == "orgA/task1/report.md"


@pytest.mark.parametrize("bad", ["", "  ", ".", "..", "a/b", "a\\b", "x\x00y"])
def test_object_key_rejects_bad_name(bad: str) -> None:
    with pytest.raises(StorageKeyError):
        object_key("orgA", "task1", bad)


@pytest.mark.parametrize("bad", ["", "..", "a/b"])
def test_object_key_rejects_bad_org_or_task(bad: str) -> None:
    with pytest.raises(StorageKeyError):
        object_key(bad, "task1", "f.txt")
    with pytest.raises(StorageKeyError):
        object_key("orgA", bad, "f.txt")


# ---------- 集成测：真实 MinIO 前缀隔离 ----------


@pytest.fixture(scope="module")
def store() -> Iterator[ObjectStore]:
    """启动临时 MinIO 容器，配置 backend 指向它，返回已建桶的 ObjectStore。"""
    try:
        from testcontainers.minio import MinioContainer
    except ImportError as exc:  # pragma: no cover
        pytest.skip(f"testcontainers[minio] 不可用：{exc}")

    try:
        container = MinioContainer()
        container.start()
    except Exception as exc:  # noqa: BLE001 - Docker 不可用即跳过
        pytest.skip(f"Docker 不可用，跳过对象存储集成测试：{exc}")

    from polis.config import get_settings

    keys = (
        "POLIS_MINIO_ENDPOINT",
        "POLIS_MINIO_ACCESS_KEY",
        "POLIS_MINIO_SECRET_KEY",
        "POLIS_MINIO_SECURE",
        "POLIS_MINIO_BUCKET",
    )
    saved = {k: os.environ.get(k) for k in keys}
    try:
        cfg = container.get_config()  # {'endpoint','access_key','secret_key'}
        os.environ["POLIS_MINIO_ENDPOINT"] = cfg["endpoint"]
        os.environ["POLIS_MINIO_ACCESS_KEY"] = cfg["access_key"]
        os.environ["POLIS_MINIO_SECRET_KEY"] = cfg["secret_key"]
        os.environ["POLIS_MINIO_SECURE"] = "false"
        os.environ["POLIS_MINIO_BUCKET"] = "polis-test"
        get_settings.cache_clear()

        s = ObjectStore()
        asyncio.run(s.ensure_bucket())
        yield s
    finally:
        container.stop()
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        get_settings.cache_clear()


def test_put_get_roundtrip(store: ObjectStore) -> None:
    org, task = f"org-{uuid.uuid4().hex[:8]}", "t1"
    payload = "供应商报价：A 公司 ¥12000".encode()

    async def _run() -> bytes:
        uri = await store.put(org, task, "quote.txt", payload, content_type="text/plain")
        assert uri == f"s3://polis-test/{org}/{task}/quote.txt"
        return await store.get(org, task, "quote.txt")

    assert asyncio.run(_run()) == payload


def test_prefix_isolation(store: ObjectStore) -> None:
    """org A 写入的对象，用 org B 前缀读不到（key 前缀天然隔离）。"""
    org_a, org_b, task = "org-aaaa", "org-bbbb", "t1"

    async def _run() -> None:
        await store.put(org_a, task, "secret.txt", b"A-only")
        # 同 task/name，但 org 前缀不同 → 读不到（NoSuchKey → StorageError）
        with pytest.raises(StorageError):
            await store.get(org_b, task, "secret.txt")
        # org A 自己能读回
        assert await store.get(org_a, task, "secret.txt") == b"A-only"

    asyncio.run(_run())


def test_presigned_and_delete(store: ObjectStore) -> None:
    org, task = "org-cccc", "t9"

    async def _run() -> None:
        await store.put(org, task, "r.md", "# 报告".encode())
        url = await store.presigned_get_url(org, task, "r.md", expires_seconds=60)
        assert url.startswith("http") and "r.md" in url
        await store.delete(org, task, "r.md")
        with pytest.raises(StorageError):
            await store.get(org, task, "r.md")

    asyncio.run(_run())
