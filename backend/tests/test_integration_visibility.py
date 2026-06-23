"""集成测试（V2-R1）：资产可见性过滤——public 全 org 可见、private 仅属主可见。"""

from __future__ import annotations

import asyncio
import uuid

from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from polis.config import get_settings
from polis.db.org_scoped import select_visible
from polis.modules.planner.models import PlanTemplate
from polis.modules.runtime.models import Skill


def _make_org(pg_url: str, name: str) -> uuid.UUID:
    engine = create_engine(pg_url.replace("+asyncpg", "+psycopg2"))
    try:
        with engine.begin() as conn:
            uid = conn.execute(
                text("INSERT INTO app_user (email) VALUES (:e) RETURNING id"),
                {"e": f"vis_{uuid.uuid4().hex[:8]}@polis.dev"},
            ).scalar()
            oid = conn.execute(
                text("INSERT INTO org (name, owner_user_id) VALUES (:n, :u) RETURNING id"),
                {"n": name, "u": uid},
            ).scalar()
            return uuid.UUID(str(oid))
    finally:
        engine.dispose()


def test_visibility_public_and_private(pg_url: str) -> None:
    org_a = _make_org(pg_url, "可见性A")
    org_b = _make_org(pg_url, "可见性B")
    sfx = uuid.uuid4().hex[:6]

    async def _run() -> None:
        engine = create_async_engine(get_settings().database_url)
        try:
            async with async_sessionmaker(engine)() as s:
                # plan_template：1 公共 + 1 A 私有
                s.add(
                    PlanTemplate(
                        name=f"pub_{sfx}", version="v1", dag_skeleton={}, visibility="public"
                    )
                )
                s.add(
                    PlanTemplate(
                        name=f"prvA_{sfx}",
                        version="v1",
                        dag_skeleton={},
                        visibility="private",
                        owner_org_id=org_a,
                    )
                )
                # skill：1 公共 + 1 A 私有
                s.add(Skill(name=f"sk_pub_{sfx}", kind="manual", visibility="public"))
                s.add(
                    Skill(
                        name=f"sk_prvA_{sfx}",
                        kind="manual",
                        visibility="private",
                        owner_org_id=org_a,
                    )
                )
                await s.flush()

                def names(rows: list) -> set[str]:  # type: ignore[type-arg]
                    return {r.name for r in rows}

                # A 见：公共 + 自己私有
                tA = names(list((await s.scalars(select_visible(PlanTemplate, org_a))).all()))
                assert f"pub_{sfx}" in tA and f"prvA_{sfx}" in tA
                # B 见：仅公共，绝不见 A 私有
                tB = names(list((await s.scalars(select_visible(PlanTemplate, org_b))).all()))
                assert f"pub_{sfx}" in tB and f"prvA_{sfx}" not in tB

                skA = names(list((await s.scalars(select_visible(Skill, org_a))).all()))
                skB = names(list((await s.scalars(select_visible(Skill, org_b))).all()))
                assert f"sk_prvA_{sfx}" in skA and f"sk_prvA_{sfx}" not in skB
                assert f"sk_pub_{sfx}" in skA and f"sk_pub_{sfx}" in skB
        finally:
            await engine.dispose()

    asyncio.run(_run())
