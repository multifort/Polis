"""集成测试（V2-S2 ④ escalate）：返工仍不达标 → escalate_node 建一条 rework 审批进收件箱。"""

from __future__ import annotations

import asyncio
import uuid

from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from polis.config import get_settings
from polis.modules.planner.workflow import escalate_node


def _seed_org(pg_url: str) -> uuid.UUID:
    engine = create_engine(pg_url.replace("+asyncpg", "+psycopg2"))
    try:
        with engine.begin() as conn:
            uid = conn.execute(
                text("INSERT INTO app_user (email) VALUES (:e) RETURNING id"),
                {"e": f"esc_{uuid.uuid4().hex[:8]}@polis.dev"},
            ).scalar()
            oid = conn.execute(
                text("INSERT INTO org (name, owner_user_id) VALUES ('纠错公司', :u) RETURNING id"),
                {"u": uid},
            ).scalar()
            return uuid.UUID(str(oid))
    finally:
        engine.dispose()


def test_escalate_node_creates_rework_approval(pg_url: str) -> None:
    org_id = _seed_org(pg_url)
    run_id = uuid.uuid4()

    async def _run() -> None:
        # escalate_node 内部 init_engine 会建全局引擎（绑定本 loop）；用完 dispose，
        # 免污染后续测试（idempotent init_engine 会复用 → "different loop"）。
        from polis.db.session import dispose_engine

        try:
            await escalate_node(str(run_id), str(org_id), "n4", 0.3)
        finally:
            await dispose_engine()

        engine = create_async_engine(get_settings().database_url)
        try:
            async with async_sessionmaker(engine)() as s:
                row = (
                    await s.execute(
                        text(
                            "SELECT kind, status, ref_id, (payload->>'node_id'), "
                            "(payload->>'judge') FROM approval WHERE org_id = :o"
                        ).bindparams(o=org_id)
                    )
                ).first()
                assert row is not None
                kind, status, ref_id, node_id, judge = row
                assert kind == "rework"
                assert status == "pending"  # 进收件箱待人审
                assert ref_id == str(run_id)
                assert node_id == "n4"
                assert float(judge) == 0.3
        finally:
            await engine.dispose()

    asyncio.run(_run())
