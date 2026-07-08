"""单元测试（M4-C）：McpRegistry / McpRuntime 桩工具。纯逻辑，无 DB。"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

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
    is_stdio_command_allowed,
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


def test_runtime_calls_mcp_sdk_stdio_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class AsyncContext:
        def __init__(self, value: object) -> None:
            self._value = value

        async def __aenter__(self) -> object:
            return self._value

        async def __aexit__(self, *_args: object) -> None:
            return None

    class Params:
        def __init__(
            self,
            *,
            command: str,
            args: list[str],
            env: dict[str, str] | None,
        ) -> None:
            captured["params"] = {"command": command, "args": args, "env": env}

    class Session:
        def __init__(self, read_stream: object, write_stream: object) -> None:
            captured["streams"] = (read_stream, write_stream)

        async def __aenter__(self) -> Session:
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def initialize(self) -> None:
            captured["initialized"] = True

        async def call_tool(self, name: str, *, arguments: dict[str, object]) -> object:
            captured["tool_call"] = {"name": name, "arguments": arguments}
            return SimpleNamespace(structuredContent={"answer": 42})

    def import_module(name: str) -> object:
        if name == "mcp":
            return SimpleNamespace(ClientSession=Session, StdioServerParameters=Params)
        if name == "mcp.client.stdio":
            return SimpleNamespace(stdio_client=lambda params: AsyncContext(("read", "write")))
        raise AssertionError(name)

    monkeypatch.setattr(mcp.importlib, "import_module", import_module)
    monkeypatch.setattr(
        mcp,
        "get_settings",
        lambda: SimpleNamespace(mcp_stdio_allowed_commands=["python"]),
    )

    reg = McpRegistry()
    reg.register(
        McpTool(
            server="browser-pilot",
            name="web_search",
            description="标准 MCP 搜索",
            parameters={"type": "object"},
            mcp_transport="stdio",
            mcp_command="python",
            mcp_args=["server.py"],
            mcp_env={"API_KEY": "handle"},
        )
    )

    out = asyncio.run(
        McpRuntime(reg).call(ToolCall(id="c6", name="web_search", arguments={"q": "风险"}))
    )

    assert out == '{"answer": 42}'
    assert captured["params"] == {
        "command": "python",
        "args": ["server.py"],
        "env": {"API_KEY": "handle"},
    }
    assert captured["streams"] == ("read", "write")
    assert captured["initialized"] is True
    assert captured["tool_call"] == {"name": "web_search", "arguments": {"q": "风险"}}


def test_runtime_rejects_unlisted_mcp_stdio_command(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        mcp,
        "get_settings",
        lambda: SimpleNamespace(mcp_stdio_allowed_commands=[]),
    )
    reg = McpRegistry()
    reg.register(
        McpTool(
            server="browser-pilot",
            name="web_search",
            description="标准 MCP 搜索",
            parameters={"type": "object"},
            mcp_transport="stdio",
            mcp_command="python",
        )
    )

    with pytest.raises(McpToolCallError, match="白名单"):
        asyncio.run(
            McpRuntime(reg).call(
                ToolCall(id="c6-denied", name="web_search", arguments={"q": "风险"})
            )
        )


def test_stdio_command_allowlist_matches_name_or_exact_path() -> None:
    assert is_stdio_command_allowed("/usr/bin/python", ["python"])
    assert is_stdio_command_allowed("/usr/bin/python", ["/usr/bin/python"])
    assert not is_stdio_command_allowed("/tmp/python", ["/usr/bin/python"])


def test_runtime_calls_mcp_sdk_sse_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class AsyncContext:
        def __init__(self, value: object) -> None:
            self._value = value

        async def __aenter__(self) -> object:
            return self._value

        async def __aexit__(self, *_args: object) -> None:
            return None

    class Session:
        def __init__(self, read_stream: object, write_stream: object) -> None:
            captured["streams"] = (read_stream, write_stream)

        async def __aenter__(self) -> Session:
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def initialize(self) -> None:
            return None

        async def call_tool(self, name: str, *, arguments: dict[str, object]) -> object:
            captured["tool_call"] = {"name": name, "arguments": arguments}
            return SimpleNamespace(content=[SimpleNamespace(text="sse-ok")])

    def sse_client(
        url: str,
        *,
        headers: dict[str, str] | None,
        timeout: float,
        sse_read_timeout: float | None,
    ) -> AsyncContext:
        captured["sse"] = {
            "url": url,
            "headers": headers,
            "timeout": timeout,
            "sse_read_timeout": sse_read_timeout,
        }
        return AsyncContext(("sse-read", "sse-write"))

    def import_module(name: str) -> object:
        if name == "mcp":
            return SimpleNamespace(ClientSession=Session)
        if name == "mcp.client.sse":
            return SimpleNamespace(sse_client=sse_client)
        raise AssertionError(name)

    monkeypatch.setattr(mcp.importlib, "import_module", import_module)

    reg = McpRegistry()
    reg.register(
        McpTool(
            server="remote",
            name="lookup",
            description="标准 MCP SSE 工具",
            parameters={"type": "object"},
            http_headers={"Authorization": "Bearer handle"},
            timeout_seconds=4.0,
            mcp_transport="sse",
            mcp_url="http://tools.local/sse",
            sse_read_timeout_seconds=9.0,
        )
    )

    out = asyncio.run(McpRuntime(reg).call(ToolCall(id="c7", name="lookup", arguments={"id": "1"})))

    assert out == "sse-ok"
    assert captured["sse"] == {
        "url": "http://tools.local/sse",
        "headers": {"Authorization": "Bearer handle"},
        "timeout": 4.0,
        "sse_read_timeout": 9.0,
    }
    assert captured["streams"] == ("sse-read", "sse-write")
    assert captured["tool_call"] == {"name": "lookup", "arguments": {"id": "1"}}


def test_runtime_calls_mcp_sdk_streamable_http_tool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class AsyncContext:
        def __init__(self, value: object) -> None:
            self._value = value

        async def __aenter__(self) -> object:
            return self._value

        async def __aexit__(self, *_args: object) -> None:
            return None

    class Session:
        def __init__(self, read_stream: object, write_stream: object) -> None:
            captured["streams"] = (read_stream, write_stream)

        async def __aenter__(self) -> Session:
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def initialize(self) -> None:
            return None

        async def call_tool(self, name: str, *, arguments: dict[str, object]) -> object:
            captured["tool_call"] = {"name": name, "arguments": arguments}
            return SimpleNamespace(content=[SimpleNamespace(text="stream-ok")])

    def streamablehttp_client(
        url: str,
        *,
        headers: dict[str, str] | None,
        timeout: float,
        sse_read_timeout: float,
    ) -> AsyncContext:
        captured["stream"] = {
            "url": url,
            "headers": headers,
            "timeout": timeout,
            "sse_read_timeout": sse_read_timeout,
        }
        return AsyncContext(("stream-read", "stream-write", lambda: "session-id"))

    def import_module(name: str) -> object:
        if name == "mcp":
            return SimpleNamespace(ClientSession=Session)
        if name == "mcp.client.streamable_http":
            return SimpleNamespace(streamablehttp_client=streamablehttp_client)
        raise AssertionError(name)

    monkeypatch.setattr(mcp.importlib, "import_module", import_module)

    reg = McpRegistry()
    reg.register(
        McpTool(
            server="remote",
            name="fetch",
            description="标准 MCP Streamable HTTP 工具",
            parameters={"type": "object"},
            timeout_seconds=6.0,
            mcp_transport="streamable_http",
            mcp_url="http://tools.local/mcp",
        )
    )

    out = asyncio.run(McpRuntime(reg).call(ToolCall(id="c8", name="fetch", arguments={"id": "2"})))

    assert out == "stream-ok"
    assert captured["stream"] == {
        "url": "http://tools.local/mcp",
        "headers": None,
        "timeout": 6.0,
        "sse_read_timeout": 300,
    }
    assert captured["streams"] == ("stream-read", "stream-write")
    assert captured["tool_call"] == {"name": "fetch", "arguments": {"id": "2"}}
