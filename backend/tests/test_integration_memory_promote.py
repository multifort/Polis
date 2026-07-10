"""集成测试（V2-B3 自动晋升）：任务产出 → role 中间层 → 频次门 → org 记忆。"""

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


def _seed_org_agent(pg_url: str) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """造 org + role + agent。返回 (org_id, role_id, agent_id)。"""
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
            role_id = conn.execute(
                text(
                    "INSERT INTO role (org_id, name, description) "
                    "VALUES (:o, '采购分析师', '供应商交付分析') RETURNING id"
                ),
                {"o": oid},
            ).scalar()
            agent_id = conn.execute(
                text(
                    "INSERT INTO agent (org_id, role_id, name, source, status) "
                    "VALUES (:o, :r, :n, 'preset', 'active') RETURNING id"
                ),
                {"o": oid, "r": role_id, "n": f"采购分析师-{uuid.uuid4().hex[:6]}"},
            ).scalar()
            return uuid.UUID(str(oid)), uuid.UUID(str(role_id)), uuid.UUID(str(agent_id))
    finally:
        engine.dispose()


def _seed_task(pg_url: str, org_id: uuid.UUID, agent_id: uuid.UUID) -> uuid.UUID:
    """造 task_run + 两条 done 产出。返回 task_id=run_id。"""
    engine = create_engine(pg_url.replace("+asyncpg", "+psycopg2"))
    try:
        with engine.begin() as conn:
            rid = conn.execute(
                text("INSERT INTO task_run (org_id, status) VALUES (:o, 'done') RETURNING id"),
                {"o": org_id},
            ).scalar()
            for nid, content in [("n1", "供应商A交付分析正文"), ("n2", "报告正文")]:
                conn.execute(
                    text(
                        "INSERT INTO result_envelope "
                        "(org_id, task_id, node_id, agent_id, status, content) "
                        "VALUES (:o, :t, :n, :a, 'done', :c)"
                    ),
                    {"o": org_id, "t": rid, "n": nid, "a": agent_id, "c": content},
                )
            return uuid.UUID(str(rid))
    finally:
        engine.dispose()


def test_promote_distills_high_confidence_to_role_then_org_by_frequency(pg_url: str) -> None:
    org_id, role_id, agent_id = _seed_org_agent(pg_url)
    task_id = _seed_task(pg_url, org_id, agent_id)

    async def _run() -> None:
        engine = create_async_engine(get_settings().database_url)
        try:
            async with async_sessionmaker(engine)() as s:
                gw = StubModelGateway(script=[ChatResponse(content=_FACTS_JSON)])
                stats = await memory_center.promote_facts_from_task(s, gw, _MODEL, org_id, task_id)
                assert stats == {
                    "distilled": 2,
                    "role_written": 1,
                    "promoted": 0,
                    "skipped": 0,
                }

                # 第一次只进入 role 中间层：高置信事实落 role，低置信丢弃，org 还未达频次门
                rows = (
                    await s.execute(
                        text(
                            "SELECT content, confidence, promoted_from, namespace, "
                            "last_promoted_at, provenance FROM memory "
                            "WHERE org_id = :o AND scope = 'role'"
                        ).bindparams(o=org_id)
                    )
                ).all()
                assert len(rows) == 1
                content, conf, promoted_from, ns, last_promoted, provenance = rows[0]
                assert "供应商A" in content
                assert conf == 0.9
                assert promoted_from == task_id  # 溯源
                assert ns == f"role:{role_id}"
                assert last_promoted is not None
                assert provenance["occurrence_count"] == 1
                assert (
                    await s.scalar(
                        text(
                            "SELECT count(*) FROM memory WHERE org_id = :o AND scope = 'org'"
                        ).bindparams(o=org_id)
                    )
                    == 0
                )

                # 幂等：再晋升同一任务 → 跳过，不重复落库
                gw2 = StubModelGateway(script=[ChatResponse(content=_FACTS_JSON)])
                stats2 = await memory_center.promote_facts_from_task(
                    s, gw2, _MODEL, org_id, task_id
                )
                assert stats2["skipped"] == 1 and stats2["promoted"] == 0
                n = await s.scalar(
                    text(
                        "SELECT count(*) FROM memory WHERE org_id = :o AND scope = 'role'"
                    ).bindparams(o=org_id)
                )
                assert n == 1

                # 第二个任务复现同一事实 → 更新 role 频次，并晋升到 org
                task_id_2 = _seed_task(pg_url, org_id, agent_id)
                gw3 = StubModelGateway(script=[ChatResponse(content=_FACTS_JSON)])
                stats3 = await memory_center.promote_facts_from_task(
                    s, gw3, _MODEL, org_id, task_id_2
                )
                assert stats3 == {
                    "distilled": 2,
                    "role_written": 1,
                    "promoted": 1,
                    "skipped": 0,
                }
                role_prov = await s.scalar(
                    text(
                        "SELECT provenance FROM memory "
                        "WHERE org_id = :o AND scope = 'role' AND namespace = :ns"
                    ).bindparams(o=org_id, ns=f"role:{role_id}")
                )
                assert role_prov["occurrence_count"] == 2
                assert sorted(role_prov["task_ids"]) == sorted([str(task_id), str(task_id_2)])

                org_rows = (
                    await s.execute(
                        text(
                            "SELECT content, confidence, promoted_from, namespace, provenance "
                            "FROM memory WHERE org_id = :o AND scope = 'org'"
                        ).bindparams(o=org_id)
                    )
                ).all()
                assert len(org_rows) == 1
                org_content, org_conf, org_promoted_from, org_ns, org_provenance = org_rows[0]
                assert "供应商A" in org_content
                assert org_conf == 0.9
                assert org_promoted_from == task_id_2
                assert org_ns == "company"
                assert org_provenance["kind"] == "role_frequency"
                assert org_provenance["role_frequency"] == 2
                await s.rollback()
        finally:
            await engine.dispose()

    asyncio.run(_run())


def test_promote_org_isolation(pg_url: str) -> None:
    """org 隔离：A 的产出晋升到 A 的 org 记忆，B 看不到。"""
    org_a, _, agent_a = _seed_org_agent(pg_url)
    task_a_1 = _seed_task(pg_url, org_a, agent_a)
    task_a_2 = _seed_task(pg_url, org_a, agent_a)
    org_b, _, _ = _seed_org_agent(pg_url)

    async def _run() -> None:
        engine = create_async_engine(get_settings().database_url)
        try:
            async with async_sessionmaker(engine)() as s:
                gw = StubModelGateway(script=[ChatResponse(content=_FACTS_JSON)])
                await memory_center.promote_facts_from_task(s, gw, _MODEL, org_a, task_a_1)
                gw2 = StubModelGateway(script=[ChatResponse(content=_FACTS_JSON)])
                await memory_center.promote_facts_from_task(s, gw2, _MODEL, org_a, task_a_2)
                # B 检索 org 记忆 → 看不到 A 的晋升事实
                slice_b = await memory_center.retrieve(
                    s, org_b, scopes=["org"], query="供应商A 交付"
                )
                assert slice_b.summaries == []
                await s.rollback()
        finally:
            await engine.dispose()

    asyncio.run(_run())
