"""集成测试（V2-P3b）：结果导出——渲染 md/pdf + 落 artifact + 直接下载。

用内存假 ObjectStore override 依赖，端点无需 live MinIO 即可测。
pdf 渲染依赖本机是否有可用中文字体（见 planner/export.py）——环境缺字体时端点返回 503，
测试对此优雅跳过 pdf 断言（不同环境字体可用性不同，不应让门禁因缺可选外部资源而红）。
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any, cast

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from polis.config import get_settings
from polis.modules.planner import export as export_mod
from polis.modules.planner import repository as planner_repo
from polis.modules.storage.client import object_key
from polis.seed import seed


class FakeStore:
    """内存对象存储替身，供导出端点脱离 live MinIO 测试。"""

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
        return self._data[object_key(org_id, task_id, name)]

    async def delete(self, org_id: str, task_id: str, name: str) -> None:
        self._data.pop(object_key(org_id, task_id, name), None)

    async def presigned_get_url(
        self, org_id: str, task_id: str, name: str, expires_seconds: int = 900
    ) -> str:
        return f"http://minio.local/{object_key(org_id, task_id, name)}"


def _register(c: Any, email: str) -> dict[str, str]:
    r = c.post("/api/auth/register", json={"email": email, "password": "secret123"})
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _provision(c: Any, auth: dict[str, str], name: str) -> str:
    r = c.post("/api/provision", json={"name": name, "preset": "采购分析公司"}, headers=auth)
    assert r.status_code == 201, r.text
    return str(r.json()["org"]["id"])


def _seed_run_with_output(org_id: uuid.UUID, goal: str) -> uuid.UUID:
    """直接建 plan + task_run + result_envelope（绕过 Temporal），返回 plan_id。"""

    async def _run() -> uuid.UUID:
        engine = create_async_engine(get_settings().database_url)
        try:
            async with async_sessionmaker(engine)() as s:
                plan = await planner_repo.create_plan(
                    s, org_id, goal=goal, dag={"nodes": []}, version="v1", estimated_cost_cents=0
                )
                run = await planner_repo.create_task_run(s, org_id, plan.id, "wf-export")
                await s.flush()
                from polis.modules.memory.models import ResultEnvelope

                s.add(
                    ResultEnvelope(
                        org_id=org_id,
                        task_id=run.id,
                        node_id="n1",
                        status="done",
                        summary="结论摘要",
                        content="结论：A 公司综合成本最低，B 公司交期 7 天被否。",
                    )
                )
                plan_id = plan.id
                await s.commit()
                return cast(uuid.UUID, plan_id)
        finally:
            await engine.dispose()

    return asyncio.run(_run())


def test_export_md(client: Any) -> None:
    from polis.main import app
    from polis.modules.storage.deps import get_object_store

    app.dependency_overrides[get_object_store] = lambda: FakeStore()
    try:
        c = client
        asyncio.run(seed())
        auth = _register(c, f"exp_{uuid.uuid4().hex[:8]}@polis.dev")
        org_id = _provision(c, auth, "导出公司")
        h = {**auth, "X-Org-Id": org_id}

        plan_id = _seed_run_with_output(uuid.UUID(org_id), "分析供应商交付准时率")

        r = c.post(f"/api/plans/{plan_id}/export", params={"fmt": "md"}, headers=h)
        assert r.status_code == 200, r.text
        assert r.headers["content-type"].startswith("text/markdown")
        assert "attachment" in r.headers["content-disposition"]
        text = r.content.decode("utf-8")
        assert "分析供应商交付准时率" in text
        assert "A 公司综合成本最低" in text
        assert "节点 n1" in text

        # fmt 非法 → 400
        bad = c.post(f"/api/plans/{plan_id}/export", params={"fmt": "docx"}, headers=h)
        assert bad.status_code == 400

        # 未启动的计划（无 task_run）→ 404
        never_run = c.post("/api/plans", json={"goal": "分析供应商交付"}, headers=h)
        assert never_run.status_code == 201
        r404 = c.post(
            f"/api/plans/{never_run.json()['id']}/export", params={"fmt": "md"}, headers=h
        )
        assert r404.status_code == 404
    finally:
        app.dependency_overrides.pop(get_object_store, None)


def test_export_pdf_when_font_available(client: Any) -> None:
    """pdf 导出：本机若无可用中文字体，端点优雅 503——本测试相应跳过，不视为门禁失败。"""
    from polis.main import app
    from polis.modules.storage.deps import get_object_store

    app.dependency_overrides[get_object_store] = lambda: FakeStore()
    try:
        c = client
        asyncio.run(seed())
        auth = _register(c, f"exp_{uuid.uuid4().hex[:8]}@polis.dev")
        org_id = _provision(c, auth, "导出公司PDF")
        h = {**auth, "X-Org-Id": org_id}

        plan_id = _seed_run_with_output(uuid.UUID(org_id), "分析供应商交付准时率")
        r = c.post(f"/api/plans/{plan_id}/export", params={"fmt": "pdf"}, headers=h)
        if r.status_code == 503:
            import pytest

            pytest.skip(f"本机无可用中文字体，PDF 导出优雅降级：{r.text}")
        assert r.status_code == 200, r.text
        assert r.headers["content-type"] == "application/pdf"
        assert r.content[:5] == b"%PDF-"
    finally:
        app.dependency_overrides.pop(get_object_store, None)


def test_build_markdown_structure() -> None:
    md = export_mod.build_markdown(
        goal="分析报价",
        status="done",
        started_at="2026-07-01T00:00:00",
        finished_at="2026-07-01T00:01:00",
        duration_seconds=60.0,
        nodes=[{"node_id": "n1", "content": "结果正文"}],
        usage={"calls": 2, "total_tokens": 100, "cost": 0.01},
    )
    assert "# 执行结果：分析报价" in md
    assert "节点 n1" in md and "结果正文" in md
    assert "LLM 调用次数：2" in md
