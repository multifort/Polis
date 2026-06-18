"""集成测试 T8.3：org_id 行级隔离回归。

以非 superuser 角色 polis_app + SET app.current_org 验证：跨租户互不可见、未设上下文 fail-closed。
"""

from __future__ import annotations

import uuid

from sqlalchemy import create_engine, text


def test_org_isolation_rls(pg_url: str) -> None:
    engine = create_engine(pg_url.replace("+asyncpg", "+psycopg2"))
    a_name = f"A-role-{uuid.uuid4().hex[:6]}"
    b_name = f"B-role-{uuid.uuid4().hex[:6]}"
    try:
        # 以 superuser 造数据（绕过 RLS）：一个用户、A/B 两公司、各一条 role 行
        with engine.begin() as conn:
            uid = conn.execute(
                text("INSERT INTO app_user (email) VALUES (:e) RETURNING id"),
                {"e": f"rls_{uuid.uuid4().hex[:8]}@polis.dev"},
            ).scalar_one()
            org_a = conn.execute(
                text("INSERT INTO org (name, owner_user_id) VALUES ('A公司', :u) RETURNING id"),
                {"u": uid},
            ).scalar_one()
            org_b = conn.execute(
                text("INSERT INTO org (name, owner_user_id) VALUES ('B公司', :u) RETURNING id"),
                {"u": uid},
            ).scalar_one()
            conn.execute(
                text("INSERT INTO role (org_id, name) VALUES (:o, :n)"),
                {"o": org_a, "n": a_name},
            )
            conn.execute(
                text("INSERT INTO role (org_id, name) VALUES (:o, :n)"),
                {"o": org_b, "n": b_name},
            )

        # 以非 superuser 角色验证 RLS
        with engine.connect() as conn:
            conn.execute(text("SET ROLE polis_app"))

            # 当前公司 = A：只见 A
            conn.execute(text("SELECT set_config('app.current_org', :v, false)"), {"v": str(org_a)})
            names = set(conn.execute(text("SELECT name FROM role")).scalars().all())
            assert a_name in names
            assert b_name not in names

            # 切到 B：只见 B
            conn.execute(text("SELECT set_config('app.current_org', :v, false)"), {"v": str(org_b)})
            names = set(conn.execute(text("SELECT name FROM role")).scalars().all())
            assert b_name in names
            assert a_name not in names

            # 未设公司上下文：fail-closed，0 行
            conn.execute(text("RESET app.current_org"))
            assert conn.execute(text("SELECT count(*) FROM role")).scalar_one() == 0

            conn.execute(text("RESET ROLE"))
    finally:
        engine.dispose()
