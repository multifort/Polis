"""集成测试（M4-B）：SkillLoader 双形态加载 + 最小权限过滤。"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from polis.config import get_settings
from polis.modules.model.gateway import ToolCall
from polis.modules.org.schemas import AgentAuthority
from polis.modules.runtime import mcp
from polis.modules.runtime.mcp import McpRegistry, McpRuntime
from polis.modules.runtime.skills import load_skills, register_bound_tools


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


def _seed_http_tool_skill(pg_url: str) -> str:
    name = f"http_tool_{uuid.uuid4().hex[:8]}"
    engine = create_engine(pg_url.replace("+asyncpg", "+psycopg2"))
    try:
        with engine.begin() as conn:
            sid = conn.execute(
                text(
                    "INSERT INTO skill (name, kind, status) VALUES (:n, 'tool', 'published') "
                    "RETURNING id"
                ),
                {"n": name},
            ).scalar()
            conn.execute(
                text(
                    "INSERT INTO skill_version (skill_id, version, content, tool, mcp_server, "
                    "io_schema, permissions) VALUES (:s, 'v1', '远端工具', :t, 'remote', "
                    ":io, :perms)"
                ),
                {
                    "s": sid,
                    "t": name,
                    "io": "{}",
                    "perms": (
                        '{"http":{"endpoint":"http://tools.local/mcp","timeout_seconds":2.5}}'
                    ),
                },
            )
    finally:
        engine.dispose()
    return name


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


def test_skill_loader_registers_http_tool_bridge(
    pg_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    name = _seed_http_tool_skill(pg_url)
    captured: dict[str, object] = {}

    class Response:
        text = ""

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"result": "bridge-ok"}

    class Client:
        def __init__(self, **kwargs: object) -> None:
            captured["client_kwargs"] = kwargs

        async def __aenter__(self) -> Client:
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def post(
            self,
            url: str,
            *,
            json: dict[str, object],
            headers: dict[str, str] | None,
        ) -> Response:
            captured["url"] = url
            captured["json"] = json
            captured["headers"] = headers
            return Response()

    monkeypatch.setattr(mcp.httpx, "AsyncClient", Client)

    async def _run() -> str:
        engine = create_async_engine(get_settings().database_url)
        try:
            async with async_sessionmaker(engine)() as s:
                loaded = await load_skills(
                    s,
                    [name],
                    AgentAuthority(allowed_tools=[name]),
                )
        finally:
            await engine.dispose()

        registry = McpRegistry()
        register_bound_tools(registry, loaded)
        tool = registry.get(name)
        assert tool is not None
        assert tool.http_endpoint == "http://tools.local/mcp"
        return await McpRuntime(registry).call(
            ToolCall(id="http", name=name, arguments={"q": "hello"})
        )

    assert asyncio.run(_run()) == "bridge-ok"
    assert captured["url"] == "http://tools.local/mcp"
    assert captured["json"] == {"server": "remote", "tool": name, "arguments": {"q": "hello"}}
    assert captured["client_kwargs"] == {"trust_env": False, "timeout": 2.5}
