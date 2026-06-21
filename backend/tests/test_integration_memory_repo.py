"""集成测试（M5-A）：memory repository 基础 SQL。"""

from __future__ import annotations

import asyncio
import uuid

from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from polis.config import get_settings
from polis.modules.memory import repository as repo


def _make_org(pg_url: str) -> uuid.UUID:
    engine = create_engine(pg_url.replace("+asyncpg", "+psycopg2"))
    try:
        with engine.begin() as conn:
            uid = conn.execute(
                text("INSERT INTO app_user (email) VALUES (:e) RETURNING id"),
                {"e": f"mem_{uuid.uuid4().hex[:8]}@polis.dev"},
            ).scalar()
            oid = conn.execute(
                text("INSERT INTO org (name, owner_user_id) VALUES ('记忆库', :u) RETURNING id"),
                {"u": uid},
            ).scalar()
            return uuid.UUID(str(oid))
    finally:
        engine.dispose()


def test_insert_list_find_touch(pg_url: str) -> None:
    org_id = _make_org(pg_url)

    async def _run() -> None:
        engine = create_async_engine(get_settings().database_url)
        try:
            async with async_sessionmaker(engine)() as s:
                m1 = await repo.insert_memory(
                    s,
                    org_id=org_id,
                    scope="org",
                    namespace="procurement",
                    mem_type="factual",
                    content="供应商A交付准时率95%",
                    provenance={"sourceUrl": "http://x", "confidence": 0.9},
                    importance=0.8,
                    confidence=0.9,
                )
                await repo.insert_memory(
                    s,
                    org_id=org_id,
                    scope="role",
                    namespace="analyst",
                    mem_type="factual",
                    content="另一条",
                )
                await s.commit()

                # 作用域过滤：只取 org 作用域
                org_rows = await repo.list_by_scope(s, org_id, ["org"])
                assert len(org_rows) == 1
                assert org_rows[0].content == "供应商A交付准时率95%"
                assert org_rows[0].embedding is None  # 桩无向量

                # namespace 过滤
                assert len(await repo.list_by_scope(s, org_id, ["org"], ["other"])) == 0

                # 内容查重
                dup = await repo.find_by_content(
                    s, org_id, "org", "procurement", "供应商A交付准时率95%"
                )
                assert dup is not None and dup.id == m1.id

                # touch last_accessed 不报错
                await repo.touch_last_accessed(s, [m1.id])
                await s.commit()
        finally:
            await engine.dispose()

    asyncio.run(_run())
