"""集成测试（M2 收尾 / T9.3）：公司改名/删除 + 所有者权限矩阵。"""

from __future__ import annotations

import asyncio
import uuid

from fastapi.testclient import TestClient

from polis.seed import seed


def _auth(client: TestClient, email: str | None = None) -> dict[str, str]:
    email = email or f"mgmt_{uuid.uuid4().hex[:8]}@polis.dev"
    r = client.post("/api/auth/register", json={"email": email, "password": "secret123"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _user_id(client: TestClient, auth: dict[str, str]) -> str:
    return client.get("/api/me", headers=auth).json()["user"]["id"]


def _invite_and_accept(
    client: TestClient, owner: dict[str, str], org_id: str, email: str, role: str = "member"
) -> dict[str, str]:
    token = client.post(
        f"/api/orgs/{org_id}/invites",
        json={"email": email, "role": role},
        headers=owner,
    ).json()["invite_token"]
    auth = _auth(client, email)
    assert client.post(f"/api/invites/{token}/accept", headers=auth).status_code == 200
    return auth


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


def test_owner_updates_org_primary_model(client: TestClient) -> None:
    asyncio.run(seed())
    owner = _auth(client)
    org_id = client.post("/api/orgs", json={"name": "主模型公司"}, headers=owner).json()["id"]

    r = client.patch(
        f"/api/orgs/{org_id}",
        json={
            "name": "主模型公司",
            "description": "默认用 pro",
            "primary_model_id": "deepseek-v4-pro",
        },
        headers=owner,
    )
    assert r.status_code == 200, r.text
    assert r.json()["primary_model_id"] == "deepseek-v4-pro"

    me = client.get("/api/me", headers=owner).json()
    org = next(o for o in me["orgs"] if o["id"] == org_id)
    assert org["primary_model_id"] == "deepseek-v4-pro"

    r = client.patch(
        f"/api/orgs/{org_id}",
        json={"name": "主模型公司", "description": "默认用 pro"},
        headers=owner,
    )
    assert r.status_code == 200, r.text
    assert r.json()["primary_model_id"] == "deepseek-v4-pro"

    r = client.patch(
        f"/api/orgs/{org_id}",
        json={"name": "主模型公司", "description": None, "primary_model_id": None},
        headers=owner,
    )
    assert r.status_code == 200, r.text
    assert r.json()["primary_model_id"] is None


def test_org_primary_model_guards(client: TestClient) -> None:
    asyncio.run(seed())
    owner = _auth(client)
    org_id = client.post("/api/orgs", json={"name": "主模型权限公司"}, headers=owner).json()["id"]

    r = client.patch(
        f"/api/orgs/{org_id}",
        json={"name": "主模型权限公司", "primary_model_id": "text-embedding-bge"},
        headers=owner,
    )
    assert r.status_code == 400

    r = client.patch(
        f"/api/orgs/{org_id}",
        json={"name": "主模型权限公司", "primary_model_id": "no-such-model"},
        headers=owner,
    )
    assert r.status_code == 404


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


def test_owner_updates_member_roles_and_protects_last_owner(client: TestClient) -> None:
    owner = _auth(client)
    owner_user_id = _user_id(client, owner)
    org_id = client.post("/api/orgs", json={"name": "角色调整公司"}, headers=owner).json()["id"]

    member_email = f"role_{uuid.uuid4().hex[:8]}@polis.dev"
    member = _invite_and_accept(client, owner, org_id, member_email)
    member_user_id = _user_id(client, member)

    r = client.patch(
        f"/api/orgs/{org_id}/members/{member_user_id}",
        json={"role": "approver"},
        headers=owner,
    )
    assert r.status_code == 200
    assert r.json()["role"] == "approver"
    me = client.get("/api/me", headers=member).json()
    assert next(o for o in me["orgs"] if o["id"] == org_id)["role"] == "approver"

    r = client.patch(
        f"/api/orgs/{org_id}/members/{owner_user_id}",
        json={"role": "member"},
        headers=owner,
    )
    assert r.status_code == 400

    r = client.patch(
        f"/api/orgs/{org_id}/members/{member_user_id}",
        json={"role": "owner"},
        headers=owner,
    )
    assert r.status_code == 200
    assert r.json()["role"] == "owner"

    r = client.patch(
        f"/api/orgs/{org_id}/members/{owner_user_id}",
        json={"role": "member"},
        headers=owner,
    )
    assert r.status_code == 200
    assert r.json()["role"] == "member"


def test_non_owner_cannot_update_member_role(client: TestClient) -> None:
    owner = _auth(client)
    owner_user_id = _user_id(client, owner)
    org_id = client.post("/api/orgs", json={"name": "非 owner 调整公司"}, headers=owner).json()[
        "id"
    ]

    member_email = f"no_role_{uuid.uuid4().hex[:8]}@polis.dev"
    member = _invite_and_accept(client, owner, org_id, member_email)

    r = client.patch(
        f"/api/orgs/{org_id}/members/{owner_user_id}",
        json={"role": "member"},
        headers=member,
    )
    assert r.status_code == 403


def test_owner_updates_agent_model_selection(client: TestClient) -> None:
    asyncio.run(seed())
    owner = _auth(client)
    provision = client.post(
        "/api/provision",
        json={"name": "模型选择公司", "preset": "采购分析公司"},
        headers=owner,
    )
    assert provision.status_code == 201, provision.text
    org_id = provision.json()["org"]["id"]
    owner_org = {**owner, "X-Org-Id": org_id}

    agents = client.get("/api/orgs/current/agents", headers=owner_org).json()
    agent = next(a for a in agents if a["name"] == "询价Agent")
    assert agent["model"] is None

    r = client.patch(
        f"/api/orgs/current/agents/{agent['id']}/model",
        json={"model_id": "deepseek-v4-pro"},
        headers=owner_org,
    )
    assert r.status_code == 200, r.text
    assert r.json()["model"] == "deepseek-v4-pro"

    agents = client.get("/api/orgs/current/agents", headers=owner_org).json()
    assert next(a for a in agents if a["id"] == agent["id"])["model"] == "deepseek-v4-pro"

    r = client.patch(
        f"/api/orgs/current/agents/{agent['id']}/model",
        json={"model_id": None},
        headers=owner_org,
    )
    assert r.status_code == 200, r.text
    assert r.json()["model"] is None


def test_agent_model_selection_guards(client: TestClient) -> None:
    asyncio.run(seed())
    owner = _auth(client)
    provision = client.post(
        "/api/provision",
        json={"name": "模型权限公司", "preset": "采购分析公司"},
        headers=owner,
    )
    assert provision.status_code == 201, provision.text
    org_id = provision.json()["org"]["id"]
    owner_org = {**owner, "X-Org-Id": org_id}
    agent = client.get("/api/orgs/current/agents", headers=owner_org).json()[0]

    member = _invite_and_accept(
        client, owner, org_id, f"agent_model_{uuid.uuid4().hex[:8]}@polis.dev"
    )
    r = client.patch(
        f"/api/orgs/current/agents/{agent['id']}/model",
        json={"model_id": "deepseek-v4-pro"},
        headers={**member, "X-Org-Id": org_id},
    )
    assert r.status_code == 403

    r = client.patch(
        f"/api/orgs/current/agents/{agent['id']}/model",
        json={"model_id": "text-embedding-bge"},
        headers=owner_org,
    )
    assert r.status_code == 400

    r = client.patch(
        f"/api/orgs/current/agents/{agent['id']}/model",
        json={"model_id": "no-such-model"},
        headers=owner_org,
    )
    assert r.status_code == 404
