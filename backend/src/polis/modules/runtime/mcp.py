"""MCP Runtime/Registry（design 04 §4）。

本地工具（echo/calc/黑板）与 HTTP MCP/tool bridge 共用同一 ToolSpec 契约。
完整 stdio/sse MCP SDK 接入后，McpRuntime.call 的外层契约仍保持不变。
"""

from __future__ import annotations

import importlib
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import httpx

from polis.config import get_settings
from polis.modules.model.gateway import ToolCall, ToolSpec


class McpToolNotFound(Exception):
    """注册表中无该工具名。"""


class McpToolCallError(Exception):
    """远端 MCP/tool 调用失败。"""


@dataclass
class McpTool:
    server: str
    name: str
    description: str
    parameters: dict[str, Any]  # JSON schema
    # 纯函数工具用 handler（echo/calc）；需 DB/任务上下文的工具用 ahandler（黑板取数）。
    handler: Callable[[dict[str, Any]], str] | None = None
    ahandler: Callable[[dict[str, Any], Any], Awaitable[str]] | None = None
    http_endpoint: str | None = None
    http_headers: dict[str, str] = field(default_factory=dict)
    timeout_seconds: float = 5.0
    mcp_transport: str | None = None  # stdio / sse / streamable_http
    mcp_url: str | None = None
    mcp_command: str | None = None
    mcp_args: list[str] = field(default_factory=list)
    mcp_env: dict[str, str] = field(default_factory=dict)
    sse_read_timeout_seconds: float | None = None


@dataclass
class McpServerConfig:
    server: str
    transport: str
    url: str | None = None
    command: str | None = None
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)
    timeout_seconds: float = 5.0
    sse_read_timeout_seconds: float | None = None


class McpRegistry:
    """可用工具注册表：name → McpTool。SkillLoader 的工具型 skill 按 name 引用这里。"""

    def __init__(self) -> None:
        self._tools: dict[str, McpTool] = {}

    def register(self, tool: McpTool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> McpTool | None:
        return self._tools.get(name)

    def list_tools(self) -> list[McpTool]:
        return list(self._tools.values())

    def specs(self) -> list[ToolSpec]:
        """转 ToolSpec 列表供模型 tool-calling。"""
        return [
            ToolSpec(name=t.name, description=t.description, parameters=t.parameters)
            for t in self._tools.values()
        ]


class McpRuntime:
    """工具执行：按 ToolCall.name 路由到注册工具。

    纯函数工具走同步 handler（echo/calc）；ctx-aware 工具走 async ahandler（黑板需 DB/任务上下文）。
    `ctx` 是执行上下文（如黑板的 session/org/task），构造时注入。
    """

    def __init__(self, registry: McpRegistry, ctx: Any | None = None) -> None:
        self._registry = registry
        self._ctx = ctx

    async def call(self, tool_call: ToolCall) -> str:
        tool = self._registry.get(tool_call.name)
        if tool is None:
            raise McpToolNotFound(tool_call.name)
        if tool.ahandler is not None:
            return await tool.ahandler(tool_call.arguments, self._ctx)
        if tool.handler is not None:
            return tool.handler(tool_call.arguments)
        if tool.http_endpoint is not None:
            return await _call_http_tool(tool, tool_call.arguments)
        if tool.mcp_transport is not None:
            return await _call_mcp_sdk_tool(tool, tool_call.arguments)
        raise McpToolNotFound(tool_call.name)


async def _call_http_tool(tool: McpTool, arguments: dict[str, Any]) -> str:
    """调用 HTTP MCP/tool bridge。

    请求体采用稳定小契约：`server`、`tool`、`arguments`；响应兼容 `content`/`result`/`text`/`output`
    字段，便于把现成 HTTP 工具服务包成 Polis 可调用工具。
    """
    endpoint = tool.http_endpoint
    if endpoint is None:
        raise McpToolNotFound(tool.name)
    payload = {"server": tool.server, "tool": tool.name, "arguments": arguments}
    try:
        async with httpx.AsyncClient(trust_env=False, timeout=tool.timeout_seconds) as client:
            resp = await client.post(endpoint, json=payload, headers=tool.http_headers or None)
            resp.raise_for_status()
    except Exception as exc:  # noqa: BLE001 - 对上层统一表现为工具调用失败。
        raise McpToolCallError(f"工具 {tool.name} HTTP 调用失败") from exc

    try:
        data = resp.json()
    except ValueError:
        return resp.text
    if not isinstance(data, dict):
        return json.dumps(data, ensure_ascii=False)
    for key in ("content", "result", "text", "output"):
        if key in data:
            value = data[key]
            return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return json.dumps(data, ensure_ascii=False)


async def _call_mcp_sdk_tool(tool: McpTool, arguments: dict[str, Any]) -> str:
    """调用标准 MCP SDK transport（stdio / SSE / Streamable HTTP）。"""
    transport = tool.mcp_transport
    if transport not in {"stdio", "sse", "streamable_http"}:
        raise McpToolCallError(f"工具 {tool.name} MCP transport 不支持：{transport}")

    try:
        mcp_pkg = cast(Any, importlib.import_module("mcp"))
        client_session = mcp_pkg.ClientSession
    except Exception as exc:  # noqa: BLE001 - 依赖缺失时给上层统一错误。
        raise McpToolCallError("MCP Python SDK 未安装，无法调用标准 MCP server") from exc

    config = _server_config_from_tool(tool)
    try:
        transport_cm = _mcp_transport_context(config, mcp_pkg)
        async with transport_cm as streams:
            read_stream, write_stream = streams[0], streams[1]
            async with client_session(read_stream, write_stream) as session:
                await session.initialize()
                result = await session.call_tool(tool.name, arguments=arguments)
    except McpToolCallError:
        raise
    except Exception as exc:  # noqa: BLE001 - 对上层统一表现为工具调用失败。
        raise McpToolCallError(f"工具 {tool.name} MCP 调用失败") from exc
    return _stringify_mcp_result(result)


async def discover_mcp_tools(config: McpServerConfig) -> list[McpTool]:
    """通过标准 MCP SDK `list_tools` 发现 server 暴露的工具，并转成 Polis McpTool 元数据。"""
    if config.transport not in {"stdio", "sse", "streamable_http"}:
        raise McpToolCallError(f"MCP transport 不支持：{config.transport}")
    try:
        mcp_pkg = cast(Any, importlib.import_module("mcp"))
        client_session = mcp_pkg.ClientSession
    except Exception as exc:  # noqa: BLE001
        raise McpToolCallError("MCP Python SDK 未安装，无法发现标准 MCP server 工具") from exc

    try:
        transport_cm = _mcp_transport_context(config, mcp_pkg)
        async with transport_cm as streams:
            read_stream, write_stream = streams[0], streams[1]
            async with client_session(read_stream, write_stream) as session:
                await session.initialize()
                result = await session.list_tools()
    except McpToolCallError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise McpToolCallError(f"MCP server {config.server} 工具发现失败") from exc
    tools = getattr(result, "tools", [])
    return [_tool_from_mcp_schema(config, raw) for raw in tools]


def _server_config_from_tool(tool: McpTool) -> McpServerConfig:
    transport = tool.mcp_transport
    if transport not in {"stdio", "sse", "streamable_http"}:
        raise McpToolCallError(f"工具 {tool.name} MCP transport 不支持：{transport}")
    return McpServerConfig(
        server=tool.server,
        transport=transport,
        url=tool.mcp_url,
        command=tool.mcp_command,
        args=tool.mcp_args,
        env=tool.mcp_env,
        headers=tool.http_headers,
        timeout_seconds=tool.timeout_seconds,
        sse_read_timeout_seconds=tool.sse_read_timeout_seconds,
    )


def _mcp_transport_context(config: McpServerConfig, mcp_pkg: Any) -> Any:
    if config.transport == "stdio":
        if not config.command:
            raise McpToolCallError(f"MCP server {config.server} 缺少 stdio command")
        _ensure_stdio_command_allowed(config.command)
        stdio_mod = importlib.import_module("mcp.client.stdio")
        params_cls = mcp_pkg.StdioServerParameters
        return stdio_mod.stdio_client(
            params_cls(
                command=config.command,
                args=config.args,
                env=config.env or None,
            )
        )
    if config.transport == "sse":
        if not config.url:
            raise McpToolCallError(f"MCP server {config.server} 缺少 SSE URL")
        sse_mod = importlib.import_module("mcp.client.sse")
        return sse_mod.sse_client(
            config.url,
            headers=config.headers or None,
            timeout=config.timeout_seconds,
            sse_read_timeout=config.sse_read_timeout_seconds or 300,
        )
    if not config.url:
        raise McpToolCallError(f"MCP server {config.server} 缺少 Streamable HTTP URL")
    stream_mod = importlib.import_module("mcp.client.streamable_http")
    return _streamable_http_context(config, stream_mod)


@asynccontextmanager
async def _streamable_http_context(config: McpServerConfig, stream_mod: Any) -> AsyncIterator[Any]:
    """Prefer the current SDK client while retaining compatibility with older MCP 1.x."""
    client_factory = getattr(stream_mod, "streamable_http_client", None)
    if callable(client_factory):
        timeout = httpx.Timeout(
            config.timeout_seconds,
            read=config.sse_read_timeout_seconds or 300,
        )
        async with (
            httpx.AsyncClient(
                headers=config.headers or None,
                timeout=timeout,
            ) as http_client,
            client_factory(config.url, http_client=http_client) as streams,
        ):
            yield streams
        return

    legacy_factory = getattr(stream_mod, "streamablehttp_client", None)
    if not callable(legacy_factory):
        raise McpToolCallError("MCP SDK 缺少 Streamable HTTP client")
    async with legacy_factory(
        config.url,
        headers=config.headers or None,
        timeout=config.timeout_seconds,
        sse_read_timeout=config.sse_read_timeout_seconds or 300,
    ) as streams:
        yield streams


def _tool_from_mcp_schema(config: McpServerConfig, raw: Any) -> McpTool:
    name = str(getattr(raw, "name", ""))
    description = getattr(raw, "description", None)
    input_schema = getattr(raw, "inputSchema", None)
    if input_schema is None:
        input_schema = getattr(raw, "input_schema", None)
    parameters = _jsonable_schema(input_schema) if input_schema is not None else {"type": "object"}
    return McpTool(
        server=config.server,
        name=name,
        description=description if isinstance(description, str) else name,
        parameters=parameters,
        http_headers=config.headers,
        timeout_seconds=config.timeout_seconds,
        mcp_transport=config.transport,
        mcp_url=config.url,
        mcp_command=config.command,
        mcp_args=config.args,
        mcp_env=config.env,
        sse_read_timeout_seconds=config.sse_read_timeout_seconds,
    )


def _jsonable_schema(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    elif hasattr(value, "dict"):
        value = value.dict()
    if isinstance(value, dict):
        return value
    return {"type": "object"}


def _stringify_mcp_result(result: Any) -> str:
    structured = getattr(result, "structuredContent", None)
    if structured is None:
        structured = getattr(result, "structured_content", None)
    if structured is not None:
        if isinstance(structured, dict) and set(structured) == {"result"}:
            return _dump_mcp_value(structured["result"])
        return _dump_mcp_value(structured)

    content = getattr(result, "content", None)
    if isinstance(content, list) and content:
        parts: list[str] = []
        for item in content:
            text = getattr(item, "text", None)
            if isinstance(text, str):
                parts.append(text)
                continue
            resource = getattr(item, "resource", None)
            resource_text = getattr(resource, "text", None)
            if isinstance(resource_text, str):
                parts.append(resource_text)
                continue
            parts.append(_dump_mcp_value(item))
        return "\n".join(parts)
    return _dump_mcp_value(result)


def _dump_mcp_value(value: Any) -> str:
    if isinstance(value, str):
        return value
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    elif hasattr(value, "dict"):
        value = value.dict()
    return json.dumps(value, ensure_ascii=False)


def is_stdio_command_allowed(command: str, allowed_commands: list[str]) -> bool:
    """stdio MCP 只允许显式白名单命令；裸命令按 basename 匹配，带路径命令必须精确匹配。"""
    command = command.strip()
    if not command:
        return False
    command_name = Path(command).name
    for allowed in allowed_commands:
        allowed = allowed.strip()
        if not allowed:
            continue
        if "/" in allowed:
            if command == allowed:
                return True
            continue
        if command_name == allowed:
            return True
    return False


def _ensure_stdio_command_allowed(command: str) -> None:
    allowed = get_settings().mcp_stdio_allowed_commands
    if not is_stdio_command_allowed(command, allowed):
        raise McpToolCallError(f"MCP stdio command 未在白名单中：{command}")


# ── 内置本地工具──────────────────────────────────────────────────────────


def _echo(args: dict[str, Any]) -> str:
    return str(args.get("text", ""))


def _calc_add(args: dict[str, Any]) -> str:
    return str(float(args.get("a", 0)) + float(args.get("b", 0)))


def default_registry() -> McpRegistry:
    """M4 默认注册表：内置 echo / calc_add 本地工具。"""
    reg = McpRegistry()
    reg.register(
        McpTool(
            server="local",
            name="echo",
            description="回显输入文本",
            parameters={
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
            handler=_echo,
        )
    )
    reg.register(
        McpTool(
            server="local",
            name="calc_add",
            description="计算两个数之和",
            parameters={
                "type": "object",
                "properties": {"a": {"type": "number"}, "b": {"type": "number"}},
                "required": ["a", "b"],
            },
            handler=_calc_add,
        )
    )
    return reg
