"""集成测试（M6-G / T6.7）：审批收件箱 创建/队列/决定 + 权限 + org 隔离。"""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient


def _user_org(client: TestClient) -> tuple[dict[str, str], str]:
    email = f"appr_{uuid.uuid4().hex[:8]}@polis.dev"
    r = client.post("/api/auth/register", json={"email": email, "password": "secret123"})
    auth = {"Authorization": f"Bearer {r.json()['access_token']}"}
    org_id = client.post("/api/orgs", json={"name": "审批公司"}, headers=auth).json()["id"]
    return auth, org_id


def test_approval_inbox_flow(client: TestClient) -> None:
    auth, org_id = _user_org(client)
    h = {**auth, "X-Org-Id": org_id}

    # 创建待审
    r = client.post(
        "/api/approvals",
        json={"kind": "dangerous_action", "ref_id": "node-x", "payload": {"act": "发布"}},
        headers=h,
    )
    assert r.status_code == 201, r.text
    aid = r.json()["id"]
    assert r.json()["status"] == "pending"

    # 非法 kind 拒绝
    assert client.post("/api/approvals", json={"kind": "bad"}, headers=h).status_code == 422

    # 队列可见
    pending = client.get("/api/approvals?status=pending", headers=h).json()
    assert any(a["id"] == aid for a in pending)

    # owner 决定通过
    d = client.post(f"/api/approvals/{aid}/decide", json={"approve": True}, headers=h)
    assert d.status_code == 200
    assert d.json()["status"] == "approved"

    # 重复决定 409
    assert (
        client.post(f"/api/approvals/{aid}/decide", json={"approve": True}, headers=h).status_code
        == 409
    )

    # 决定后不在 pending 队列
    pending2 = client.get("/api/approvals?status=pending", headers=h).json()
    assert all(a["id"] != aid for a in pending2)


def test_approval_org_isolation(client: TestClient) -> None:
    auth_a, org_a = _user_org(client)
    auth_b, org_b = _user_org(client)
    ha, hb = {**auth_a, "X-Org-Id": org_a}, {**auth_b, "X-Org-Id": org_b}

    aid = client.post("/api/approvals", json={"kind": "plan", "ref_id": "p1"}, headers=ha).json()[
        "id"
    ]

    # B 看不到 A 的待审；B 决定 A 的 → 404
    assert all(a["id"] != aid for a in client.get("/api/approvals", headers=hb).json())
    assert (
        client.post(f"/api/approvals/{aid}/decide", json={"approve": True}, headers=hb).status_code
        == 404
    )
