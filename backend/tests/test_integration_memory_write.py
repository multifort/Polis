"""集成测试（M5-B）：写入管线 write_facts —— 去噪/去重/评分/出处入库。"""

from __future__ import annotations

import asyncio
import uuid

from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from polis.config import get_settings
from polis.modules.memory import repository as repo
from polis.modules.memory.center import Fact, write_facts
from polis.modules.model.gateway import StubModelGateway


def _make_org(pg_url: str) -> uuid.UUID:
    engine = create_engine(pg_url.replace("+asyncpg", "+psycopg2"))
    try:
        with engine.begin() as conn:
            uid = conn.execute(
                text("INSERT INTO app_user (email) VALUES (:e) RETURNING id"),
                {"e": f"mw_{uuid.uuid4().hex[:8]}@polis.dev"},
            ).scalar()
            oid = conn.execute(
                text("INSERT INTO org (name, owner_user_id) VALUES ('写库', :u) RETURNING id"),
                {"u": uid},
            ).scalar()
            return uuid.UUID(str(oid))
    finally:
        engine.dispose()


def test_write_pipeline_filters_and_scores(pg_url: str) -> None:
    org_id = _make_org(pg_url)

    async def _run() -> None:
        engine = create_async_engine(get_settings().database_url)
        try:
            async with async_sessionmaker(engine)() as s:
                facts = [
                    Fact(
                        content="  供应商A   交付准时率 95%  ",
                        confidence=0.9,
                        importance=0.8,
                        provenance={"sourceUrl": "http://a", "confidence": 0.9},
                    ),
                    Fact(
                        content="供应商A 交付准时率 95%", confidence=0.9, importance=0.8
                    ),  # 规范化后与上重复
                    Fact(content="...", confidence=0.5, importance=0.5),  # 噪声（纯标点）
                    Fact(content="供应商B 报价偏高", confidence=0.5, importance=0.4),
                ]
                written = await write_facts(s, StubModelGateway(), org_id, "role", "analyst", facts)

                # 去重(2条同内容→1) + 去噪(纯标点剔除) → 实际写入 2 条
                assert len(written) == 2
                contents = {m.content for m in written}
                assert "供应商A 交付准时率 95%" in contents  # 标准化折叠空白
                assert "供应商B 报价偏高" in contents

                # 评分 = importance×confidence；出处入库；embedding 桩为 None
                rows = await repo.list_by_scope(s, org_id, ["role"], ["analyst"])
                assert len(rows) == 2
                a = next(m for m in rows if m.content.startswith("供应商A"))
                assert abs(a.importance - 0.8 * 0.9) < 1e-6
                assert a.provenance == {"sourceUrl": "http://a", "confidence": 0.9}
                assert a.embedding is None
        finally:
            await engine.dispose()

    asyncio.run(_run())
