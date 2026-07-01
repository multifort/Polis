"""MinIO/S3 兼容对象存储客户端（薄封装）。

设计：v2/05 §9（对象存储引入·fork2）、§16.2（附件注入时序）。
- 所有寻址经 `object_key(org_id, task_id, name)` → `{org_id}/{task_id}/{name}`，限定在 org 前缀内；
- 组件做路径穿越校验，杜绝越权寻址到别的 org 前缀；
- 底层 minio SDK 为同步，异步方法用 `asyncio.to_thread` 包装，不阻塞事件循环；
- 凭证从 `Settings` 读（env 注入），永不落日志/入库。
"""

from __future__ import annotations

import asyncio
import io
from datetime import timedelta
from typing import TYPE_CHECKING

from polis.config import get_settings

if TYPE_CHECKING:
    from minio import Minio


class StorageError(Exception):
    """对象存储未配置/不可用，或底层操作失败。"""


class StorageKeyError(StorageError):
    """key 组件非法（空、含 '/'、路径穿越等）。"""


def _validate_component(field: str, value: str) -> str:
    """校验单个 key 组件：非空、不含分隔符/穿越/空字节。"""
    v = value.strip()
    if not v:
        raise StorageKeyError(f"{field} 不能为空")
    if v in (".", "..") or "/" in v or "\\" in v or "\x00" in v:
        raise StorageKeyError(f"{field} 含非法字符：{value!r}")
    return v


def object_key(org_id: str, task_id: str, name: str) -> str:
    """构造多租户隔离的对象 key：`{org_id}/{task_id}/{name}`。

    org_id/task_id/name 三段均经穿越校验（禁 '/'、'..'），确保寻址不逃逸出本 org 前缀。
    """
    org = _validate_component("org_id", str(org_id))
    task = _validate_component("task_id", str(task_id))
    fname = _validate_component("name", str(name))
    return f"{org}/{task}/{fname}"


class ObjectStore:
    """MinIO/S3 客户端封装。put/get/delete/presigned 全部经 `object_key` 前缀寻址。"""

    def __init__(self) -> None:
        s = get_settings()
        if not (s.minio_endpoint and s.minio_access_key and s.minio_secret_key):
            raise StorageError("MinIO 未配置（需 POLIS_MINIO_ENDPOINT/ACCESS_KEY/SECRET_KEY）")
        try:
            from minio import Minio
        except ImportError as exc:  # pragma: no cover - 依赖缺失
            raise StorageError("缺少 minio 依赖，请 `uv sync`") from exc

        self._bucket = s.minio_bucket
        self._client: Minio = Minio(
            s.minio_endpoint,
            access_key=s.minio_access_key,
            secret_key=s.minio_secret_key,
            secure=s.minio_secure,
        )

    @property
    def bucket(self) -> str:
        return self._bucket

    def uri(self, key: str) -> str:
        """对象 key → 存库用的 `s3://{bucket}/{key}` uri（写入 artifact_descriptor.uri）。"""
        return f"s3://{self._bucket}/{key}"

    # ---- 建桶（幂等）----
    def _ensure_bucket_sync(self) -> None:
        if not self._client.bucket_exists(self._bucket):
            self._client.make_bucket(self._bucket)

    async def ensure_bucket(self) -> None:
        """幂等建桶（启动时调用）。"""
        try:
            await asyncio.to_thread(self._ensure_bucket_sync)
        except Exception as exc:  # noqa: BLE001 - 归一为领域异常
            raise StorageError(f"建桶失败：{exc}") from exc

    # ---- 上传 ----
    async def put(
        self,
        org_id: str,
        task_id: str,
        name: str,
        data: bytes,
        content_type: str = "application/octet-stream",
    ) -> str:
        """上传对象到 `{org_id}/{task_id}/{name}`，返回 s3 uri。"""
        key = object_key(org_id, task_id, name)

        def _do() -> None:
            self._client.put_object(
                self._bucket,
                key,
                io.BytesIO(data),
                length=len(data),
                content_type=content_type,
            )

        try:
            await asyncio.to_thread(_do)
        except Exception as exc:  # noqa: BLE001
            raise StorageError(f"上传失败（{key}）：{exc}") from exc
        return self.uri(key)

    # ---- 下载 ----
    async def get(self, org_id: str, task_id: str, name: str) -> bytes:
        """读取对象内容（仅限本 org/task 前缀）。"""
        key = object_key(org_id, task_id, name)

        def _do() -> bytes:
            resp = self._client.get_object(self._bucket, key)
            try:
                data: bytes = resp.read()
                return data
            finally:
                resp.close()
                resp.release_conn()

        try:
            return await asyncio.to_thread(_do)
        except Exception as exc:  # noqa: BLE001
            raise StorageError(f"下载失败（{key}）：{exc}") from exc

    # ---- 删除 ----
    async def delete(self, org_id: str, task_id: str, name: str) -> None:
        key = object_key(org_id, task_id, name)
        try:
            await asyncio.to_thread(self._client.remove_object, self._bucket, key)
        except Exception as exc:  # noqa: BLE001
            raise StorageError(f"删除失败（{key}）：{exc}") from exc

    # ---- 临时下载链接 ----
    async def presigned_get_url(
        self, org_id: str, task_id: str, name: str, expires_seconds: int = 900
    ) -> str:
        """签发短时（默认 15min）预签名下载 URL，不做公开读。"""
        key = object_key(org_id, task_id, name)
        try:
            url: str = await asyncio.to_thread(
                self._client.presigned_get_object,
                self._bucket,
                key,
                timedelta(seconds=expires_seconds),
            )
            return url
        except Exception as exc:  # noqa: BLE001
            raise StorageError(f"签发下载链接失败（{key}）：{exc}") from exc
