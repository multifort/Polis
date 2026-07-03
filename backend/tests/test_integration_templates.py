"""R3 场景模板沉淀：存为模板、场景库筛选、可见性与即时 embedding。"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from polis.main import app
from polis.modules.model.gateway import ChatMessage, ChatResponse, ResolvedModel, ToolSpec
from polis.modules.planner.api import get_template_embedding_gateway
from polis.seed import seed


class FakeEmbeddingGateway:
    async def chat(
        self,
        model: ResolvedModel,
        messages: list[ChatMessage],
        tools: list[ToolSpec] | None = None,
        cred: Any | None = None,
        max_tokens: int | None = None,
    ) -> ChatResponse:
        return ChatResponse(content="")

    async def embed(self, texts: list[str]) -> list[list[float] | None]:
        return [[0.01] * 1024 for _ in texts]


def _auth(client: TestClient, prefix: str = "tpl") -> dict[str, str]:
    email = f"{prefix}_{uuid.uuid4().hex[:8]}@polis.dev"
    r = client.post("/api/auth/register", json={"email": email, "password": "secret123"})
    assert r.status_code == 201
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _saved_template_has_embedding(pg_url: str, name: str) -> bool:
    engine = create_engine(pg_url.replace("+asyncpg", "+psycopg2"))
    try:
        with engine.begin() as conn:
            found = conn.execute(
                text(
                    "SELECT embedding IS NOT NULL FROM plan_template "
                    "WHERE name = :name ORDER BY version DESC LIMIT 1"
                ),
                {"name": name},
            ).scalar()
            return bool(found)
    finally:
        engine.dispose()


def test_save_as_template_catalog_visibility_and_embedding(client: TestClient, pg_url: str) -> None:
    asyncio.run(seed())
    app.dependency_overrides[get_template_embedding_gateway] = lambda: FakeEmbeddingGateway()
    try:
        auth = _auth(client, "tpl_a")
        pr = client.post(
            "/api/provision", json={"name": "模板沉淀公司", "preset": "采购分析公司"}, headers=auth
        )
        assert pr.status_code == 201, pr.text
        org_id = pr.json()["org"]["id"]
        h = {**auth, "X-Org-Id": org_id}

        plan = client.post("/api/plans", json={"goal": "分析供应商交付"}, headers=h)
        assert plan.status_code == 201, plan.text
        plan_id = plan.json()["id"]
        tpl_name = f"私有场景-{uuid.uuid4().hex[:6]}"

        first = client.post(
            f"/api/plans/{plan_id}/save-as-template",
            json={"name": tpl_name, "domain": "procurement", "subcategory": "supplier"},
            headers=h,
        )
        assert first.status_code == 201, first.text
        assert first.json()["source"] == "user_saved"
        assert first.json()["visibility"] == "private"
        assert first.json()["version"] == "1.0"
        assert _saved_template_has_embedding(pg_url, tpl_name)

        second = client.post(
            f"/api/plans/{plan_id}/save-as-template",
            json={"name": tpl_name, "domain": "data", "subcategory": "analysis"},
            headers=h,
        )
        assert second.status_code == 201, second.text
        assert second.json()["version"] == "1.1"

        catalog = client.get("/api/catalog/templates?domain=data", headers=h)
        assert catalog.status_code == 200, catalog.text
        matches = [r for r in catalog.json() if r["name"] == tpl_name]
        assert len(matches) == 1
        assert matches[0]["subcategory"] == "analysis"

        # 另一个 org 只能看 public 模板，不能看 A org 的私有沉淀模板。
        auth_b = _auth(client, "tpl_b")
        org_b = client.post("/api/orgs", json={"name": "模板隔离公司"}, headers=auth_b)
        assert org_b.status_code == 201, org_b.text
        hb = {**auth_b, "X-Org-Id": org_b.json()["id"]}
        catalog_b = client.get("/api/catalog/templates", headers=hb)
        assert catalog_b.status_code == 200, catalog_b.text
        assert tpl_name not in {r["name"] for r in catalog_b.json()}
    finally:
        app.dependency_overrides.pop(get_template_embedding_gateway, None)
