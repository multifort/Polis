"""单元测试（M4-C）：McpRegistry / McpRuntime 桩工具。纯逻辑，无 DB。"""

from __future__ import annotations

import asyncio

import pytest

from polis.modules.model.gateway import ToolCall
from polis.modules.runtime import mcp
from polis.modules.runtime.mcp import (
    McpRegistry,
    McpRuntime,
    McpTool,
    McpToolCallError,
    McpToolNotFound,
    default_registry,
)


def test_registry_lists_builtin_specs() -> None:
    reg = default_registry()
    names = {s.name for s in reg.specs()}
    assert {"echo", "calc_add"} <= names


def test_runtime_calls_echo() -> None:
    rt = McpRuntime(default_registry())
    out = asyncio.run(rt.call(ToolCall(id="c1", name="echo", arguments={"text": "hi"})))
    assert out == "hi"


def test_runtime_calls_calc_add() -> None:
    rt = McpRuntime(default_registry())
    out = asyncio.run(rt.call(ToolCall(id="c2", name="calc_add", arguments={"a": 2, "b": 3})))
    assert out == "5.0"


def test_runtime_unknown_tool_raises() -> None:
    rt = McpRuntime(default_registry())
    with pytest.raises(McpToolNotFound):
        asyncio.run(rt.call(ToolCall(id="c3", name="nope", arguments={})))


def test_runtime_calls_http_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class Response:
        text = ""

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"content": "远端结果"}

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

    reg = McpRegistry()
    reg.register(
        McpTool(
            server="browser-pilot",
            name="web_search",
            description="远端搜索",
            parameters={"type": "object"},
            http_endpoint="http://tools.local/mcp",
            http_headers={"X-Tool": "polis"},
            timeout_seconds=3.0,
        )
    )
    out = asyncio.run(
        McpRuntime(reg).call(
            ToolCall(id="c4", name="web_search", arguments={"query": "供应商风险"})
        )
    )

    assert out == "远端结果"
    assert captured["url"] == "http://tools.local/mcp"
    assert captured["headers"] == {"X-Tool": "polis"}
    assert captured["json"] == {
        "server": "browser-pilot",
        "tool": "web_search",
        "arguments": {"query": "供应商风险"},
    }
    assert captured["client_kwargs"] == {"trust_env": False, "timeout": 3.0}


def test_runtime_http_tool_failure_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    class Client:
        def __init__(self, **_kwargs: object) -> None:
            return None

        async def __aenter__(self) -> Client:
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def post(self, *_args: object, **_kwargs: object) -> object:
            raise RuntimeError("down")

    monkeypatch.setattr(mcp.httpx, "AsyncClient", Client)

    reg = McpRegistry()
    reg.register(
        McpTool(
            server="remote",
            name="remote_tool",
            description="远端工具",
            parameters={"type": "object"},
            http_endpoint="http://tools.local/mcp",
        )
    )
    with pytest.raises(McpToolCallError):
        asyncio.run(McpRuntime(reg).call(ToolCall(id="c5", name="remote_tool", arguments={})))
