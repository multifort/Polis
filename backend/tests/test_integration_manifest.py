"""集成测试（M6-F / T6.6）：Run Manifest 落库 + 复现查询。"""

from __future__ import annotations

import asyncio
import uuid

from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from polis.config import get_settings
from polis.modules.observability import repository as obs_repo


def _make_org_plan_run(pg_url: str) -> tuple[uuid.UUID, uuid.UUID]:
    """造 org + plan + task_run，返回 (org_id, task_run_id)。"""
    engine = create_engine(pg_url.replace("+asyncpg", "+psycopg2"))
    try:
        with engine.begin() as conn:
            uid = conn.execute(
                text("INSERT INTO app_user (email) VALUES (:e) RETURNING id"),
                {"e": f"mf_{uuid.uuid4().hex[:8]}@polis.dev"},
            ).scalar()
            oid = conn.execute(
                text("INSERT INTO org (name, owner_user_id) VALUES ('清单库', :u) RETURNING id"),
                {"u": uid},
            ).scalar()
            pid = conn.execute(
                text(
                    "INSERT INTO plan (org_id, goal, dag, version) "
                    "VALUES (:o, 'g', '{}', 'v1') RETURNING id"
                ),
                {"o": oid},
            ).scalar()
            rid = conn.execute(
                text(
                    "INSERT INTO task_run (org_id, plan_id, temporal_workflow_id, status) "
                    "VALUES (:o, :p, 'wf', 'running') RETURNING id"
                ),
                {"o": oid, "p": pid},
            ).scalar()
            return uuid.UUID(str(oid)), uuid.UUID(str(rid))
    finally:
        engine.dispose()


def test_manifest_create_and_get(pg_url: str) -> None:
    org_id, task_id = _make_org_plan_run(pg_url)

    async def _run() -> None:
        engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as s:
                await obs_repo.create_run_manifest(
                    s,
                    task_id=task_id,
                    org_id=org_id,
                    plan_snapshot={"workflow_name": "wf", "nodes": [{"id": "n1"}]},
                    plan_version="v1",
                    models_used={"chat": "deepseek-v4-pro"},
                    agents_used={"n1": ["procurement.rfq"]},
                )
                await s.commit()

                mf = await obs_repo.get_run_manifest(s, org_id, task_id)
                assert mf is not None
                assert mf.plan_version == "v1"
                assert mf.models_used == {"chat": "deepseek-v4-pro"}
                assert mf.agents_used == {"n1": ["procurement.rfq"]}
                assert mf.plan_snapshot["nodes"][0]["id"] == "n1"
                assert mf.started_at is not None
        finally:
            await engine.dispose()

    asyncio.run(_run())
