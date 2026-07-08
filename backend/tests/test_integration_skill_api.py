"""集成测试（TD-034）：公司主动提交 manual Skill 草稿 + 人审发布。"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any, cast

from sqlalchemy import create_engine, text

if TYPE_CHECKING:
    from fastapi.testclient import TestClient


def _register(c: Any, email: str) -> dict[str, str]:
    r = c.post("/api/auth/register", json={"email": email, "password": "secret123"})
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _create_org(c: Any, auth: dict[str, str], name: str) -> str:
    r = c.post("/api/orgs", json={"name": name, "charter": "技能仓库测试"}, headers=auth)
    assert r.status_code == 201, r.text
    return str(r.json()["id"])


def _scalar(pg_url: str, sql: str, **params: object) -> object:
    engine = create_engine(pg_url.replace("+asyncpg", "+psycopg2"))
    try:
        with engine.connect() as conn:
            return conn.execute(text(sql), params).scalar_one_or_none()
    finally:
        engine.dispose()


def test_create_manual_skill_draft_then_review_publish(client: TestClient, pg_url: str) -> None:
    c = cast(Any, client)
    auth = _register(c, f"skill_{uuid.uuid4().hex[:8]}@polis.dev")
    org_id = _create_org(c, auth, "技能提交公司")
    headers = {**auth, "X-Org-Id": org_id}

    payload = {
        "name": f"manual.supplier.delivery.{uuid.uuid4().hex[:6]}",
        "capability": "procurement.delivery_review",
        "content": (
            "步骤1：收集供应商交付记录。步骤2：按准时率、延误原因和风险等级整理结论。"
            "步骤3：输出可执行建议。"
        ),
    }
    created = c.post("/api/skills", json=payload, headers=headers)
    assert created.status_code == 201, created.text
    skill = created.json()
    assert skill["status"] == "draft"
    assert skill["trust"] == "private"
    assert skill["visibility"] == "org"
    assert skill["review_status"] == "pending"
    assert "步骤1" in skill["content_preview"]

    listed = c.get("/api/skills?mine_only=true", headers=headers)
    assert listed.status_code == 200, listed.text
    assert any(
        row["id"] == skill["id"] and row["review_status"] == "pending" for row in listed.json()
    )

    approvals = c.get("/api/approvals?status=pending", headers=headers)
    assert approvals.status_code == 200, approvals.text
    review = next(row for row in approvals.json() if row["ref_id"] == skill["id"])
    assert review["kind"] == "skill_review"
    assert review["payload"]["source"] == "user_submitted"

    decided = c.post(
        f"/api/approvals/{review['id']}/decide",
        json={"approve": True},
        headers=headers,
    )
    assert decided.status_code == 200, decided.text

    assert (
        _scalar(pg_url, "SELECT status FROM skill WHERE id = :skill_id", skill_id=skill["id"])
        == "published"
    )
    assert (
        _scalar(pg_url, "SELECT trust FROM skill WHERE id = :skill_id", skill_id=skill["id"])
        == "verified"
    )

    published = c.get("/api/skills?status=published&mine_only=true", headers=headers)
    assert published.status_code == 200, published.text
    assert any(row["id"] == skill["id"] for row in published.json())


def test_update_manual_skill_draft_refreshes_review(client: TestClient, pg_url: str) -> None:
    c = cast(Any, client)
    auth = _register(c, f"skill_edit_{uuid.uuid4().hex[:8]}@polis.dev")
    org_id = _create_org(c, auth, "技能编辑公司")
    headers = {**auth, "X-Org-Id": org_id}
    suffix = uuid.uuid4().hex[:6]

    created = c.post(
        "/api/skills",
        json={
            "name": f"manual.edit.{suffix}",
            "capability": "procurement.old_review",
            "content": "旧步骤：收集交付记录，整理风险，输出建议。这段内容足够长用于创建草稿。",
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    skill_id = created.json()["id"]

    updated_content = (
        "新步骤1：收集供应商交付记录。新步骤2：按准时率、延误原因和赔付条款评分。"
        "新步骤3：输出继续合作、降额或暂停合作建议。"
    )
    updated = c.patch(
        f"/api/skills/{skill_id}",
        json={
            "name": f"manual.edit.updated.{suffix}",
            "capability": "procurement.delivery_review",
            "content": updated_content,
        },
        headers=headers,
    )
    assert updated.status_code == 200, updated.text
    body = updated.json()
    assert body["name"] == f"manual.edit.updated.{suffix}"
    assert body["capability"] == "procurement.delivery_review"
    assert body["review_status"] == "pending"
    assert "新步骤1" in body["content_preview"]

    assert (
        _scalar(pg_url, "SELECT name FROM skill WHERE id = :skill_id", skill_id=skill_id)
        == f"manual.edit.updated.{suffix}"
    )
    assert (
        _scalar(
            pg_url,
            "SELECT content FROM skill_version WHERE skill_id = :skill_id",
            skill_id=skill_id,
        )
        == updated_content
    )

    approvals = c.get("/api/approvals?status=pending", headers=headers)
    assert approvals.status_code == 200, approvals.text
    review = next(row for row in approvals.json() if row["ref_id"] == skill_id)
    assert review["payload"]["skill_name"] == f"manual.edit.updated.{suffix}"
    assert review["payload"]["capability"] == "procurement.delivery_review"
    assert "新步骤1" in review["payload"]["preview"]


def test_published_manual_skill_cannot_be_edited_directly(client: TestClient, pg_url: str) -> None:
    c = cast(Any, client)
    auth = _register(c, f"skill_published_{uuid.uuid4().hex[:8]}@polis.dev")
    org_id = _create_org(c, auth, "技能已发布公司")
    headers = {**auth, "X-Org-Id": org_id}

    created = c.post(
        "/api/skills",
        json={
            "name": f"manual.published.{uuid.uuid4().hex[:6]}",
            "capability": "procurement.published_review",
            "content": "发布前步骤：收集数据、形成结论、输出建议。这段内容足够长用于创建草稿。",
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    skill_id = created.json()["id"]

    approvals = c.get("/api/approvals?status=pending", headers=headers)
    review = next(row for row in approvals.json() if row["ref_id"] == skill_id)
    decided = c.post(
        f"/api/approvals/{review['id']}/decide",
        json={"approve": True},
        headers=headers,
    )
    assert decided.status_code == 200, decided.text

    denied = c.patch(
        f"/api/skills/{skill_id}",
        json={"content": "试图直接改写已发布 Skill，应被拒绝。这段内容足够长。"},
        headers=headers,
    )
    assert denied.status_code == 409
    assert (
        _scalar(pg_url, "SELECT status FROM skill WHERE id = :skill_id", skill_id=skill_id)
        == "published"
    )


def test_manual_skill_draft_is_private_to_owner_org(client: TestClient) -> None:
    c = cast(Any, client)
    suffix = uuid.uuid4().hex[:8]
    auth_a = _register(c, f"skill_a_{suffix}@polis.dev")
    auth_b = _register(c, f"skill_b_{suffix}@polis.dev")
    org_a = _create_org(c, auth_a, "技能 A 公司")
    org_b = _create_org(c, auth_b, "技能 B 公司")
    h_a = {**auth_a, "X-Org-Id": org_a}
    h_b = {**auth_b, "X-Org-Id": org_b}

    payload = {
        "name": f"manual.private.{suffix}",
        "capability": "private.capability",
        "content": (
            "这是一份只属于 A 公司的私有操作手册，包含足够长的步骤说明，"
            "等待审批前不可被其他公司看到。"
        ),
    }
    created = c.post("/api/skills", json=payload, headers=h_a)
    assert created.status_code == 201, created.text
    skill_id = created.json()["id"]

    own = c.get("/api/skills?mine_only=true", headers=h_a)
    assert any(row["id"] == skill_id for row in own.json())

    other = c.get("/api/skills", headers=h_b)
    assert other.status_code == 200, other.text
    assert all(row["id"] != skill_id for row in other.json())

    duplicate = c.post("/api/skills", json=payload, headers=h_a)
    assert duplicate.status_code == 409
