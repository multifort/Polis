"""集成测试（V2-P2b-1）：任务附件上传入口——上传 → MinIO(假) → artifact 登记 → 下载/删除。

用内存假 ObjectStore override 依赖，端点无需 live MinIO 即可测；真实 MinIO 已在
test_storage_prefix 覆盖。重点验证：附件挂到正确任务前缀、任务间不串、下载链接、删除清理。
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any, cast

from polis.modules.storage.client import StorageError, object_key
from polis.seed import seed


class FakeStore:
    """内存对象存储替身，key 用真实 object_key 构造（复用前缀隔离逻辑）。"""

    def __init__(self) -> None:
        self._data: dict[str, bytes] = {}

    def uri(self, key: str) -> str:
        return f"s3://polis/{key}"

    async def ensure_bucket(self) -> None:
        return None

    async def put(
        self, org_id: str, task_id: str, name: str, data: bytes, content_type: str = ""
    ) -> str:
        key = object_key(org_id, task_id, name)
        self._data[key] = data
        return self.uri(key)

    async def get(self, org_id: str, task_id: str, name: str) -> bytes:
        key = object_key(org_id, task_id, name)
        if key not in self._data:
            raise StorageError(f"not found: {key}")
        return self._data[key]

    async def delete(self, org_id: str, task_id: str, name: str) -> None:
        self._data.pop(object_key(org_id, task_id, name), None)

    async def presigned_get_url(
        self, org_id: str, task_id: str, name: str, expires_seconds: int = 900
    ) -> str:
        return f"http://minio.local/{object_key(org_id, task_id, name)}?e={expires_seconds}"


def _auth(c: Any, email: str) -> dict[str, str]:
    r = c.post("/api/auth/register", json={"email": email, "password": "secret123"})
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _make_task(c: Any, h: dict[str, str], name: str) -> str:
    r = c.post("/api/tasks", json={"name": name, "goal": "分析"}, headers=h)
    assert r.status_code == 201, r.text
    return cast(str, r.json()["id"])


def test_attachment_lifecycle_and_task_isolation(client: Any) -> None:
    from polis.main import app
    from polis.modules.storage.deps import get_object_store

    fake = FakeStore()
    app.dependency_overrides[get_object_store] = lambda: fake
    try:
        asyncio.run(seed())
        c = client
        auth = _auth(c, f"att_{uuid.uuid4().hex[:8]}@polis.dev")
        org_id = c.post(
            "/api/provision", json={"name": "采购", "preset": "采购分析公司"}, headers=auth
        ).json()["org"]["id"]
        h = {**auth, "X-Org-Id": org_id}

        task_a = _make_task(c, h, "任务A")
        task_b = _make_task(c, h, "任务B")

        # ① 上传附件到任务 A
        payload = "供应商报价：A 公司 ¥12000".encode()
        r = c.post(
            f"/api/tasks/{task_a}/attachments",
            files={"file": ("quote.txt", payload, "text/plain")},
            data={"field": "报价单"},
            headers=h,
        )
        assert r.status_code == 201, r.text
        att = r.json()
        assert att["filename"] == "quote.txt"
        assert att["size"] == len(payload)
        assert att["field"] == "报价单"
        assert att["uri"] == f"s3://polis/{org_id}/{task_a}/quote.txt"

        # ② 任务 A 列表含它；任务 B 列表为空（附件不串任务）
        la = c.get(f"/api/tasks/{task_a}/attachments", headers=h).json()
        assert [a["filename"] for a in la] == ["quote.txt"]
        lb = c.get(f"/api/tasks/{task_b}/attachments", headers=h).json()
        assert lb == []

        # ③ 下载链接（预签名，短时）
        u = c.get(f"/api/tasks/{task_a}/attachments/quote.txt/url", headers=h)
        assert u.status_code == 200
        assert "quote.txt" in u.json()["url"] and u.json()["expires_seconds"] == 900

        # ④ 同名覆盖：再传不产生重复登记行
        c.post(
            f"/api/tasks/{task_a}/attachments",
            files={"file": ("quote.txt", b"v2", "text/plain")},
            headers=h,
        )
        la2 = c.get(f"/api/tasks/{task_a}/attachments", headers=h).json()
        assert len(la2) == 1 and la2[0]["size"] == 2

        # ⑤ 删除 → 204；列表空；下载 404
        d = c.delete(f"/api/tasks/{task_a}/attachments/quote.txt", headers=h)
        assert d.status_code == 204
        assert c.get(f"/api/tasks/{task_a}/attachments", headers=h).json() == []
        assert c.get(f"/api/tasks/{task_a}/attachments/quote.txt/url", headers=h).status_code == 404
    finally:
        app.dependency_overrides.pop(get_object_store, None)


def test_upload_guards(client: Any) -> None:
    from polis.main import app
    from polis.modules.storage.deps import get_object_store

    app.dependency_overrides[get_object_store] = lambda: FakeStore()
    try:
        asyncio.run(seed())
        c = client
        auth = _auth(c, f"att_{uuid.uuid4().hex[:8]}@polis.dev")
        org_id = c.post(
            "/api/provision", json={"name": "采购", "preset": "采购分析公司"}, headers=auth
        ).json()["org"]["id"]
        h = {**auth, "X-Org-Id": org_id}
        task = _make_task(c, h, "任务")

        # 不存在任务 → 404
        r = c.post(
            f"/api/tasks/{uuid.uuid4()}/attachments",
            files={"file": ("f.txt", b"x", "text/plain")},
            headers=h,
        )
        assert r.status_code == 404

        # 空文件 → 400
        r = c.post(
            f"/api/tasks/{task}/attachments",
            files={"file": ("empty.txt", b"", "text/plain")},
            headers=h,
        )
        assert r.status_code == 400
    finally:
        app.dependency_overrides.pop(get_object_store, None)


def test_run_task_requires_declared_attachments(client: Any) -> None:
    """input_schema 声明必填附件时，运行任务前先挡（P2b-2）：缺附件 → 422 报缺失项。"""
    from polis.main import app
    from polis.modules.storage.deps import get_object_store

    app.dependency_overrides[get_object_store] = lambda: FakeStore()
    try:
        asyncio.run(seed())
        c = client
        auth = _auth(c, f"att_{uuid.uuid4().hex[:8]}@polis.dev")
        org_id = c.post(
            "/api/provision", json={"name": "采购", "preset": "采购分析公司"}, headers=auth
        ).json()["org"]["id"]
        h = {**auth, "X-Org-Id": org_id}

        r = c.post(
            "/api/tasks",
            json={
                "name": "带必填附件的任务",
                "goal": "分析报价",
                "input_schema": {
                    "attachments": [{"field": "quote", "label": "供应商报价单", "required": True}]
                },
            },
            headers=h,
        )
        assert r.status_code == 201, r.text
        task_id = r.json()["id"]

        # 未传附件就运行 → 422，报缺失的 label
        run = c.post(f"/api/tasks/{task_id}/run", headers=h)
        assert run.status_code == 422, run.text
        assert "供应商报价单" in str(run.json()["detail"])

        # 补传附件（field 匹配）后不再因「缺附件」被拦（后续是否成功依赖 Temporal，不在本测试范围）
        c.post(
            f"/api/tasks/{task_id}/attachments",
            files={"file": ("quote.csv", b"A,12000", "text/csv")},
            data={"field": "quote"},
            headers=h,
        )
        run2 = c.post(f"/api/tasks/{task_id}/run", headers=h)
        assert run2.status_code != 422 or "缺少必填附件" not in str(run2.json().get("detail", ""))
    finally:
        app.dependency_overrides.pop(get_object_store, None)
