"""集成测试（M3-B）：模板优先 Planner——立邦采购公司→POST /api/plans→4 节点全路由。"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient

from polis.modules.planner.errors import NoTemplateMatch
from polis.seed import seed


def _auth(client: TestClient) -> dict[str, str]:
    email = f"plan_{uuid.uuid4().hex[:8]}@polis.dev"
    r = client.post("/api/auth/register", json={"email": email, "password": "secret123"})
    assert r.status_code == 201
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_plan_from_template(client: TestClient) -> None:
    asyncio.run(seed())  # 确保预设 + 计划模板在库
    auth = _auth(client)

    # 立邦采购分析公司
    pr = client.post(
        "/api/provision", json={"name": "采购公司", "preset": "采购分析公司"}, headers=auth
    )
    assert pr.status_code == 201
    org_id = pr.json()["org"]["id"]
    org_h = {**auth, "X-Org-Id": org_id}

    # 出图
    resp = client.post("/api/plans", json={"goal": "分析供应商交付"}, headers=org_h)
    assert resp.status_code == 201, resp.text
    body = resp.json()

    assert body["status"] == "draft"
    assert body["template"] == "supplier_analysis_v1"
    assert body["goal"] == "分析供应商交付"
    assert body["dag"]["goal"] == "分析供应商交付"
    assert len(body["dag"]["nodes"]) == 4
    assert body["estimated_cost_cents"] > 0
    assert uuid.UUID(body["id"])

    routing = body["routing"]
    assert set(routing.keys()) == {"n1", "n2", "n3", "n4"}
    assert all(routing[n] is not None for n in ("n1", "n2", "n3", "n4"))


def test_plan_no_template_match(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    auth = _auth(client)

    async def _no_match(*_args: Any, **_kwargs: Any) -> Any:
        raise NoTemplateMatch

    monkeypatch.setattr("polis.modules.planner.api.service.plan", _no_match)

    # API 层仍需把领域异常翻译为 404；TD-032 的真实生成路径由 skillgen 集成测试覆盖。
    org_id = client.post("/api/orgs", json={"name": "空公司"}, headers=auth).json()["id"]
    resp = client.post("/api/plans", json={"goal": "随便"}, headers={**auth, "X-Org-Id": org_id})
    assert resp.status_code == 404
