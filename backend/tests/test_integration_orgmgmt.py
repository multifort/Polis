"""集成测试（M2 收尾 / T9.3）：公司改名/删除 + 所有者权限矩阵。"""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient


def _auth(client: TestClient) -> dict[str, str]:
    email = f"mgmt_{uuid.uuid4().hex[:8]}@polis.dev"
    r = client.post("/api/auth/register", json={"email": email, "password": "secret123"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_org_rename_delete_and_owner_guard(client: TestClient) -> None:
    owner = _auth(client)
    org_id = client.post("/api/orgs", json={"name": "待改公司"}, headers=owner).json()["id"]

    # 所有者编辑（名+描述）→ 200，描述持久化
    r = client.patch(
        f"/api/orgs/{org_id}",
        json={"name": "已改公司", "description": "做采购分析的"},
        headers=owner,
    )
    assert r.status_code == 200
    assert r.json()["name"] == "已改公司"
    assert r.json()["description"] == "做采购分析的"
    me = client.get("/api/me", headers=owner).json()
    assert next(o for o in me["orgs"] if o["id"] == org_id)["description"] == "做采购分析的"

    # 成员列表：创建者为 owner
    members = client.get(f"/api/orgs/{org_id}/members", headers=owner).json()
    assert len(members) == 1 and members[0]["role"] == "owner"

    # 非成员（另一用户）改名/删除/查成员 → 403
    assert client.get(f"/api/orgs/{org_id}/members", headers=_auth(client)).status_code == 403
    other = _auth(client)
    assert client.patch(f"/api/orgs/{org_id}", json={"name": "X"}, headers=other).status_code == 403
    assert client.delete(f"/api/orgs/{org_id}", headers=other).status_code == 403

    # 所有者删除 → 204；/me 不再包含
    assert client.delete(f"/api/orgs/{org_id}", headers=owner).status_code == 204
    me = client.get("/api/me", headers=owner).json()
    assert all(o["id"] != org_id for o in me["orgs"])
