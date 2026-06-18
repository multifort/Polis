"""集成测试（批次B / T2.8）：立邦闭环——选预设→实例化花名册→花名册 RLS 可见。"""

from __future__ import annotations

import asyncio
import uuid

from fastapi.testclient import TestClient

from polis.seed import seed


def _auth(client: TestClient) -> dict[str, str]:
    email = f"prov_{uuid.uuid4().hex[:8]}@polis.dev"
    r = client.post("/api/auth/register", json={"email": email, "password": "secret123"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_provision_from_preset(client: TestClient) -> None:
    asyncio.run(seed())  # 确保采购预设在库
    auth = _auth(client)

    # 立邦：关键词匹配到「采购分析公司」预设
    pr = client.post(
        "/api/provision", json={"name": "我的采购公司", "keyword": "采购 供应商"}, headers=auth
    )
    assert pr.status_code == 201
    body = pr.json()
    assert body["preset"].startswith("采购分析公司")
    assert {a["name"] for a in body["agents"]} == {"询价Agent", "分析Agent", "报告Agent"}

    org_id = body["org"]["id"]
    org_h = {**auth, "X-Org-Id": org_id}

    # 花名册（org-scoped, RLS）：3 个 active 的预设 Agent
    agents = client.get("/api/orgs/current/agents", headers=org_h).json()
    assert len(agents) == 3
    assert all(a["status"] == "active" and a["source"] == "preset" for a in agents)

    # 角色也建出 3 个
    roles = client.get("/api/orgs/current/roles", headers=org_h).json()
    assert len(roles) == 3

    # 精确指定预设名也可立邦
    pr2 = client.post(
        "/api/provision", json={"name": "二号公司", "preset": "采购分析公司"}, headers=auth
    )
    assert pr2.status_code == 201

    # 关键词无匹配 → 404
    pr3 = client.post("/api/provision", json={"name": "X", "keyword": "完全不相关"}, headers=auth)
    assert pr3.status_code == 404
