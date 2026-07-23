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
    """复用本地 MinIO S3 API，不为每轮测试创建新容器。"""
    from polis.config import get_settings

    settings = get_settings()
    if settings.minio_endpoint.rsplit(":", 1)[-1] != "9000":
        pytest.fail("MinIO 集成测试必须连接 S3 API 9000 端口；9001 仅用于 Web 控制台")
    if not (settings.minio_access_key and settings.minio_secret_key):
        pytest.fail("请在 backend/.env 配置现有 MinIO 的 access/secret key")

    bucket_key = "POLIS_MINIO_BUCKET"
    saved_bucket = os.environ.get(bucket_key)
    try:
        os.environ[bucket_key] = "polis-test"
        get_settings.cache_clear()

        object_store = ObjectStore()
        asyncio.run(object_store.ensure_bucket())
        yield object_store
    finally:
        if saved_bucket is None:
            os.environ.pop(bucket_key, None)
        else:
            os.environ[bucket_key] = saved_bucket
        get_settings.cache_clear()


def test_put_get_roundtrip(store: ObjectStore) -> None:
    org, task = f"org-{uuid.uuid4().hex[:8]}", "t1"
    payload = "供应商报价：A 公司 ¥12000".encode()

    async def _run() -> bytes:
        uri = await store.put(org, task, "quote.txt", payload, content_type="text/plain")
        assert uri == f"s3://polis-test/{org}/{task}/quote.txt"
        result = await store.get(org, task, "quote.txt")
        await store.delete(org, task, "quote.txt")
        return result

    assert asyncio.run(_run()) == payload


def test_prefix_isolation(store: ObjectStore) -> None:
    """org A 写入的对象，用 org B 前缀读不到（key 前缀天然隔离）。"""
    suffix = uuid.uuid4().hex[:8]
    org_a, org_b, task = f"org-a-{suffix}", f"org-b-{suffix}", "t1"

    async def _run() -> None:
        await store.put(org_a, task, "secret.txt", b"A-only")
        # 同 task/name，但 org 前缀不同 → 读不到（NoSuchKey → StorageError）
        with pytest.raises(StorageError):
            await store.get(org_b, task, "secret.txt")
        # org A 自己能读回
        assert await store.get(org_a, task, "secret.txt") == b"A-only"
        await store.delete(org_a, task, "secret.txt")

    asyncio.run(_run())


def test_presigned_and_delete(store: ObjectStore) -> None:
    org, task = f"org-c-{uuid.uuid4().hex[:8]}", "t9"

    async def _run() -> None:
        await store.put(org, task, "r.md", "# 报告".encode())
        url = await store.presigned_get_url(org, task, "r.md", expires_seconds=60)
        assert url.startswith("http") and "r.md" in url
        await store.delete(org, task, "r.md")
        with pytest.raises(StorageError):
            await store.get(org, task, "r.md")

    asyncio.run(_run())
