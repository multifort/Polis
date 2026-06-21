"""集成测试（M5-D）：decay_and_cleanup + upsert_shared_fact 并发裁决。"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from polis.config import get_settings
from polis.modules.memory import repository as repo
from polis.modules.memory.center import Fact, upsert_shared_fact
from polis.modules.model.gateway import StubModelGateway


def _make_org(pg_url: str) -> uuid.UUID:
    engine = create_engine(pg_url.replace("+asyncpg", "+psycopg2"))
    try:
        with engine.begin() as conn:
            uid = conn.execute(
                text("INSERT INTO app_user (email) VALUES (:e) RETURNING id"),
                {"e": f"md_{uuid.uuid4().hex[:8]}@polis.dev"},
            ).scalar()
            oid = conn.execute(
                text("INSERT INTO org (name, owner_user_id) VALUES ('衰减库', :u) RETURNING id"),
                {"u": uid},
            ).scalar()
            return uuid.UUID(str(oid))
    finally:
        engine.dispose()


def test_decay_deletes_low_value_and_expired(pg_url: str) -> None:
    org_id = _make_org(pg_url)

    async def _run() -> None:
        engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as s:
                # 低价值 event（importance 衰减后 <0.05）
                await repo.insert_memory(
                    s,
                    org_id=org_id,
                    scope="task",
                    namespace="t",
                    mem_type="event",
                    content="低价值事件",
                    importance=0.04,
                )
                # 过期记忆
                await repo.insert_memory(
                    s,
                    org_id=org_id,
                    scope="session",
                    namespace="t",
                    mem_type="factual",
                    content="过期会话",
                    importance=0.9,
                    expires_at=datetime.now(UTC) - timedelta(days=1),
                )
                # 正常保留
                await repo.insert_memory(
                    s,
                    org_id=org_id,
                    scope="org",
                    namespace="t",
                    mem_type="factual",
                    content="重要事实",
                    importance=0.9,
                )
                await s.commit()

                stats = await repo.decay_and_cleanup(s)
                await s.commit()
                assert stats["low_value_deleted"] >= 1
                assert stats["expired_deleted"] >= 1

                remaining = {
                    m.content
                    for m in await repo.list_by_scope(s, org_id, ["task", "session", "org"])
                }
                assert "重要事实" in remaining
                assert "低价值事件" not in remaining
                assert "过期会话" not in remaining
        finally:
            await engine.dispose()

    asyncio.run(_run())


def test_upsert_shared_fact_insert_override_conflict(pg_url: str) -> None:
    org_id = _make_org(pg_url)

    async def _run() -> None:
        gw = StubModelGateway()
        engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as s:
                # 首次 → inserted
                action, _ = await upsert_shared_fact(
                    s,
                    gw,
                    org_id,
                    "procurement",
                    Fact(content="供应商A最优", confidence=0.5, importance=0.6),
                )
                assert action == "inserted"

                # 更高置信 → overridden
                action, mem = await upsert_shared_fact(
                    s,
                    gw,
                    org_id,
                    "procurement",
                    Fact(content="供应商A最优", confidence=0.9, importance=0.6),
                )
                assert action == "overridden"
                assert mem.confidence == 0.9

                # 更低置信 → conflict 标记（不静默合并）
                action, mem = await upsert_shared_fact(
                    s,
                    gw,
                    org_id,
                    "procurement",
                    Fact(content="供应商A最优", confidence=0.3, importance=0.6),
                )
                assert action == "conflict"
                assert mem.provenance is not None and mem.provenance.get("conflict") is True
                assert mem.confidence == 0.9  # 未被低置信覆盖
        finally:
            await engine.dispose()

    asyncio.run(_run())
