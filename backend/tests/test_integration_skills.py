"""集成测试（M4-B）：SkillLoader 双形态加载 + 最小权限过滤。"""

from __future__ import annotations

import asyncio
import uuid

from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from polis.config import get_settings
from polis.modules.org.schemas import AgentAuthority
from polis.modules.runtime.skills import load_skills


def _seed_skills(pg_url: str) -> dict[str, str]:
    """插入一个 manual + 两个 tool 技能（含版本）。返回唯一名字便于断言。"""
    sfx = uuid.uuid4().hex[:8]
    names = {
        "manual": f"playbook_{sfx}",
        "allowed": f"search_{sfx}",
        "denied": f"delete_{sfx}",
    }
    engine = create_engine(pg_url.replace("+asyncpg", "+psycopg2"))
    try:
        with engine.begin() as conn:
            for key, kind in (("manual", "manual"), ("allowed", "tool"), ("denied", "tool")):
                sid = conn.execute(
                    text(
                        "INSERT INTO skill (name, kind, status) VALUES (:n, :k, 'published') "
                        "RETURNING id"
                    ),
                    {"n": names[key], "k": kind},
                ).scalar()
                if kind == "manual":
                    conn.execute(
                        text(
                            "INSERT INTO skill_version (skill_id, version, content) "
                            "VALUES (:s, 'v1', :c)"
                        ),
                        {"s": sid, "c": f"手册正文 {names[key]}"},
                    )
                else:
                    conn.execute(
                        text(
                            "INSERT INTO skill_version (skill_id, version, tool, mcp_server, "
                            "io_schema) VALUES (:s, 'v1', :t, 'local', :io)"
                        ),
                        {"s": sid, "t": names[key], "io": "{}"},
                    )
    finally:
        engine.dispose()
    return names


def test_skill_loader_manual_and_min_privilege(pg_url: str) -> None:
    names = _seed_skills(pg_url)

    async def _run() -> None:
        engine = create_async_engine(get_settings().database_url)
        try:
            async with async_sessionmaker(engine)() as s:
                loaded = await load_skills(
                    s,
                    [names["manual"], names["allowed"], names["denied"], "ghost_skill"],
                    AgentAuthority(allowed_tools=[names["allowed"]]),  # 只授权 allowed
                )
        finally:
            await engine.dispose()

        # manual 进 system_append
        assert names["manual"] in loaded.system_append
        # 授权的 tool 加载、未授权的被过滤、缺失的跳过
        tool_names = {t.tool for t in loaded.tools}
        assert names["allowed"] in tool_names
        assert names["denied"] not in tool_names
        assert len(loaded.tools) == 1

    asyncio.run(_run())
