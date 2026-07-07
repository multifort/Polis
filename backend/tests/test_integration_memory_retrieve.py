"""集成测试（M5-C）：检索管线 retrieve —— 作用域过滤 + 相关性排序 + 摘要。"""

from __future__ import annotations

import asyncio
import uuid

from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from polis.config import get_settings
from polis.modules.memory import repository as repo
from polis.modules.memory.center import retrieve
from polis.modules.model.gateway import StubModelGateway


class ReverseRerankGateway(StubModelGateway):
    async def rerank(self, query: str, documents: list[str], limit: int) -> list[int] | None:
        return list(reversed(range(len(documents))))[:limit]


def _make_org(pg_url: str) -> uuid.UUID:
    engine = create_engine(pg_url.replace("+asyncpg", "+psycopg2"))
    try:
        with engine.begin() as conn:
            uid = conn.execute(
                text("INSERT INTO app_user (email) VALUES (:e) RETURNING id"),
                {"e": f"mr_{uuid.uuid4().hex[:8]}@polis.dev"},
            ).scalar()
            oid = conn.execute(
                text("INSERT INTO org (name, owner_user_id) VALUES ('检索库', :u) RETURNING id"),
                {"u": uid},
            ).scalar()
            return uuid.UUID(str(oid))
    finally:
        engine.dispose()


def test_retrieve_scope_filter_and_relevance(pg_url: str) -> None:
    org_id = _make_org(pg_url)

    async def _run() -> None:
        engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as s:
                await repo.insert_memory(
                    s,
                    org_id=org_id,
                    scope="role",
                    namespace="analyst",
                    mem_type="factual",
                    content="供应商A交付准时率95%",
                    provenance={"sourceUrl": "http://a"},
                    importance=0.8,
                )
                await repo.insert_memory(
                    s,
                    org_id=org_id,
                    scope="role",
                    namespace="analyst",
                    mem_type="factual",
                    content="天气晴朗适合郊游",
                    importance=0.9,  # importance 高但与查询无关
                )
                await repo.insert_memory(
                    s,
                    org_id=org_id,
                    scope="session",
                    namespace="x",
                    mem_type="event",
                    content="供应商交付相关会话",
                    importance=0.5,  # session 作用域，应被过滤
                )
                await s.commit()

                sl = await retrieve(
                    s, org_id, scopes=["role", "org"], namespaces=None, query="供应商交付", limit=5
                )

                # session 作用域被排除
                assert all("会话" not in x for x in sl.summaries)
                # 相关性优先：供应商交付那条排第一（虽然另一条 importance 更高）
                assert sl.summaries[0] == "供应商A交付准时率95%"
                assert sl.provenance[0] == {"sourceUrl": "http://a"}
                assert sl.to_text().startswith("- 供应商A")
        finally:
            await engine.dispose()

    asyncio.run(_run())


def test_retrieve_uses_gateway_rerank_when_available(pg_url: str) -> None:
    org_id = _make_org(pg_url)

    async def _run() -> None:
        engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as s:
                await repo.insert_memory(
                    s,
                    org_id=org_id,
                    scope="role",
                    namespace="analyst",
                    mem_type="factual",
                    content="供应商A交付准时率95%",
                    importance=0.8,
                )
                await repo.insert_memory(
                    s,
                    org_id=org_id,
                    scope="role",
                    namespace="analyst",
                    mem_type="factual",
                    content="供应商B报价偏高",
                    importance=0.7,
                )
                await s.commit()

                local = await retrieve(s, org_id, scopes=["role"], query="供应商A 交付", limit=2)
                reranked = await retrieve(
                    s,
                    org_id,
                    scopes=["role"],
                    query="供应商A 交付",
                    gateway=ReverseRerankGateway(),
                    limit=2,
                )

                assert local.summaries[0] == "供应商A交付准时率95%"
                assert reranked.summaries[0] == "供应商B报价偏高"
        finally:
            await engine.dispose()

    asyncio.run(_run())


def test_retrieve_empty_when_no_memory(pg_url: str) -> None:
    org_id = _make_org(pg_url)

    async def _run() -> None:
        engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as s:
                sl = await retrieve(s, org_id, scopes=["role"], query="任何", limit=5)
                assert sl.summaries == []
                assert sl.to_text() == ""
        finally:
            await engine.dispose()

    asyncio.run(_run())
