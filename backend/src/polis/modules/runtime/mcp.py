"""MCP Runtime/Registry（design 04 §4）。

本地工具（echo/calc/黑板）与 HTTP MCP/tool bridge 共用同一 ToolSpec 契约。
完整 stdio/sse MCP SDK 接入后，McpRuntime.call 的外层契约仍保持不变。
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

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
