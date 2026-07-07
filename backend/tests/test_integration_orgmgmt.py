"""集成测试（M2 收尾 / T9.3）：公司改名/删除 + 所有者权限矩阵。"""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient


def _auth(client: TestClient, email: str | None = None) -> dict[str, str]:
    email = email or f"mgmt_{uuid.uuid4().hex[:8]}@polis.dev"
    r = client.post("/api/auth/register", json={"email": email, "password": "secret123"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _user_id(client: TestClient, auth: dict[str, str]) -> str:
    return client.get("/api/me", headers=auth).json()["user"]["id"]


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


def test_owner_invites_user_and_user_accepts(client: TestClient) -> None:
    owner = _auth(client)
    org_id = client.post("/api/orgs", json={"name": "邀请测试公司"}, headers=owner).json()["id"]

    invitee_email = f"invitee_{uuid.uuid4().hex[:8]}@polis.dev"
    r = client.post(
        f"/api/orgs/{org_id}/invites",
        json={"email": invitee_email, "role": "member"},
        headers=owner,
    )
    assert r.status_code == 201
    token = r.json()["invite_token"]
    assert token
    assert r.json()["status"] == "pending"

    invitee = _auth(client, invitee_email)
    r = client.post(f"/api/invites/{token}/accept", headers=invitee)
    assert r.status_code == 200
    assert r.json()["email"] == invitee_email
    assert r.json()["role"] == "member"

    me = client.get("/api/me", headers=invitee).json()
    assert next(o for o in me["orgs"] if o["id"] == org_id)["role"] == "member"

    members = client.get(f"/api/orgs/{org_id}/members", headers=owner).json()
    assert any(m["email"] == invitee_email and m["role"] == "member" for m in members)


def test_accept_invite_rejects_invalid_token(client: TestClient) -> None:
    user = _auth(client)
    r = client.post("/api/invites/not-a-real-token/accept", headers=user)
    assert r.status_code == 400


def test_member_cannot_invite_or_remove_members(client: TestClient) -> None:
    owner = _auth(client)
    owner_user_id = _user_id(client, owner)
    org_id = client.post("/api/orgs", json={"name": "权限测试公司"}, headers=owner).json()["id"]

    invitee_email = f"member_{uuid.uuid4().hex[:8]}@polis.dev"
    token = client.post(
        f"/api/orgs/{org_id}/invites",
        json={"email": invitee_email, "role": "member"},
        headers=owner,
    ).json()["invite_token"]
    member = _auth(client, invitee_email)
    assert client.post(f"/api/invites/{token}/accept", headers=member).status_code == 200

    r = client.post(
        f"/api/orgs/{org_id}/invites",
        json={"email": f"x_{uuid.uuid4().hex[:8]}@polis.dev", "role": "member"},
        headers=member,
    )
    assert r.status_code == 403

    r = client.delete(f"/api/orgs/{org_id}/members/{owner_user_id}", headers=member)
    assert r.status_code == 403


def test_owner_removes_member_and_keeps_last_owner(client: TestClient) -> None:
    owner = _auth(client)
    owner_user_id = _user_id(client, owner)
    org_id = client.post("/api/orgs", json={"name": "移除测试公司"}, headers=owner).json()["id"]

    invitee_email = f"remove_{uuid.uuid4().hex[:8]}@polis.dev"
    token = client.post(
        f"/api/orgs/{org_id}/invites",
        json={"email": invitee_email, "role": "approver"},
        headers=owner,
    ).json()["invite_token"]
    member = _auth(client, invitee_email)
    assert client.post(f"/api/invites/{token}/accept", headers=member).status_code == 200
    member_user_id = _user_id(client, member)

    r = client.delete(f"/api/orgs/{org_id}/members/{member_user_id}", headers=owner)
    assert r.status_code == 204
    me = client.get("/api/me", headers=member).json()
    assert all(o["id"] != org_id for o in me["orgs"])

    r = client.delete(f"/api/orgs/{org_id}/members/{owner_user_id}", headers=owner)
    assert r.status_code == 400


def test_inviting_existing_member_is_idempotent(client: TestClient) -> None:
    owner = _auth(client)
    org_id = client.post("/api/orgs", json={"name": "幂等邀请公司"}, headers=owner).json()["id"]

    invitee_email = f"idempotent_{uuid.uuid4().hex[:8]}@polis.dev"
    token = client.post(
        f"/api/orgs/{org_id}/invites",
        json={"email": invitee_email, "role": "member"},
        headers=owner,
    ).json()["invite_token"]
    invitee = _auth(client, invitee_email)
    assert client.post(f"/api/invites/{token}/accept", headers=invitee).status_code == 200

    r = client.post(
        f"/api/orgs/{org_id}/invites",
        json={"email": invitee_email, "role": "approver"},
        headers=owner,
    )
    assert r.status_code == 201
    assert r.json()["status"] == "accepted"
    assert r.json()["role"] == "member"
    assert r.json()["invite_token"] is None

    members = [
        m
        for m in client.get(f"/api/orgs/{org_id}/members", headers=owner).json()
        if m["email"] == invitee_email
    ]
    assert len(members) == 1
