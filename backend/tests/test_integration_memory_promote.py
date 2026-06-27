"""集成测试（V2-B3 自动晋升）：任务产出 → 蒸馏 → 高置信晋升到 org 记忆（无人 curate）。"""

from __future__ import annotations

import asyncio
import uuid

from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from polis.config import get_settings
from polis.modules.memory import center as memory_center
from polis.modules.model.gateway import ChatResponse, ResolvedModel, StubModelGateway

_MODEL = ResolvedModel(id="m", provider="p", litellm_name="n", context_window=8000)
# 蒸馏 LLM 输出：一条高置信(应晋升) + 一条低置信(应丢)
_FACTS_JSON = (
    '[{"content":"供应商A近一个月交付准时率仅 60%，风险高","confidence":0.9},'
    '{"content":"本次分析在周三下午进行","confidence":0.3}]'
)


def _seed(pg_url: str) -> tuple[uuid.UUID, uuid.UUID]:
    """造 org + task_run + 两条 done 产出。返回 (org_id, task_id=run_id)。"""
    engine = create_engine(pg_url.replace("+asyncpg", "+psycopg2"))
    try:
        with engine.begin() as conn:
            uid = conn.execute(
                text("INSERT INTO app_user (email) VALUES (:e) RETURNING id"),
                {"e": f"pm_{uuid.uuid4().hex[:8]}@polis.dev"},
            ).scalar()
            oid = conn.execute(
                text("INSERT INTO org (name, owner_user_id) VALUES ('晋升公司', :u) RETURNING id"),
                {"u": uid},
            ).scalar()
            rid = conn.execute(
                text("INSERT INTO task_run (org_id, status) VALUES (:o, 'done') RETURNING id"),
                {"o": oid},
            ).scalar()
            for nid, content in [("n1", "供应商A交付分析正文"), ("n2", "报告正文")]:
                conn.execute(
                    text(
                        "INSERT INTO result_envelope (org_id, task_id, node_id, status, content) "
                        "VALUES (:o, :t, :n, 'done', :c)"
                    ),
                    {"o": oid, "t": rid, "n": nid, "c": content},
                )
            return uuid.UUID(str(oid)), uuid.UUID(str(rid))
    finally:
        engine.dispose()


def test_promote_distills_high_confidence_to_org(pg_url: str) -> None:
    org_id, task_id = _seed(pg_url)

    async def _run() -> None:
        engine = create_async_engine(get_settings().database_url)
        try:
            async with async_sessionmaker(engine)() as s:
                gw = StubModelGateway(script=[ChatResponse(content=_FACTS_JSON)])
                stats = await memory_center.promote_facts_from_task(s, gw, _MODEL, org_id, task_id)
                assert stats == {"distilled": 2, "promoted": 1, "skipped": 0}

                # org 记忆只落了高置信那条，带溯源
                rows = (
                    await s.execute(
                        text(
                            "SELECT content, confidence, promoted_from, namespace, "
                            "last_promoted_at FROM memory WHERE org_id = :o AND scope = 'org'"
                        ).bindparams(o=org_id)
                    )
                ).all()
                assert len(rows) == 1
                content, conf, promoted_from, ns, last_promoted = rows[0]
                assert "供应商A" in content
                assert conf == 0.9
                assert promoted_from == task_id  # 溯源
                assert ns == "company"
                assert last_promoted is not None

                # 幂等：再晋升同一任务 → 跳过，不重复落库
                gw2 = StubModelGateway(script=[ChatResponse(content=_FACTS_JSON)])
                stats2 = await memory_center.promote_facts_from_task(
                    s, gw2, _MODEL, org_id, task_id
                )
                assert stats2["skipped"] == 1 and stats2["promoted"] == 0
                n = await s.scalar(
                    text(
                        "SELECT count(*) FROM memory WHERE org_id = :o AND scope = 'org'"
                    ).bindparams(o=org_id)
                )
                assert n == 1
                await s.rollback()
        finally:
            await engine.dispose()

    asyncio.run(_run())


def test_promote_org_isolation(pg_url: str) -> None:
    """org 隔离：A 的产出晋升到 A 的 org 记忆，B 看不到。"""
    org_a, task_a = _seed(pg_url)
    org_b, _ = _seed(pg_url)

    async def _run() -> None:
        engine = create_async_engine(get_settings().database_url)
        try:
            async with async_sessionmaker(engine)() as s:
                gw = StubModelGateway(script=[ChatResponse(content=_FACTS_JSON)])
                await memory_center.promote_facts_from_task(s, gw, _MODEL, org_a, task_a)
                # B 检索 org 记忆 → 看不到 A 的晋升事实
                slice_b = await memory_center.retrieve(
                    s, org_b, scopes=["org"], query="供应商A 交付"
                )
                assert slice_b.summaries == []
                await s.rollback()
        finally:
            await engine.dispose()

    asyncio.run(_run())
