"""对象存储的 FastAPI 依赖：默认注入真实 `ObjectStore`；测试可 override 成内存假实现。"""

from __future__ import annotations

from typing import Annotated, Protocol

from fastapi import Depends, HTTPException, status

from polis.modules.storage.client import ObjectStore, StorageError


class ObjectStoreLike(Protocol):
    """ObjectStore 的最小接口（便于测试替身）。"""

    def uri(self, key: str) -> str: ...
    async def ensure_bucket(self) -> None: ...
    async def put(
        self, org_id: str, task_id: str, name: str, data: bytes, content_type: str = ...
    ) -> str: ...
    async def get(self, org_id: str, task_id: str, name: str) -> bytes: ...
    async def delete(self, org_id: str, task_id: str, name: str) -> None: ...
    async def presigned_get_url(
        self, org_id: str, task_id: str, name: str, expires_seconds: int = ...
    ) -> str: ...


def get_object_store() -> ObjectStoreLike:
    """构造对象存储客户端。MinIO 未配置时转 503（而非未捕获异常→裸 500）。"""
    try:
        return ObjectStore()
    except StorageError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc


ObjectStoreDep = Annotated[ObjectStoreLike, Depends(get_object_store)]
