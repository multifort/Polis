"""MCP Runtime/Registry（design 04 §4）。

M4 桩：注册「本地工具」(echo/calc) 作可调通工具，验证 _loop 工具调用链路（ADR-0007）。
真实外部 MCP server（browser-pilot 等 stdio/sse）留后续——届时 McpRuntime.call 内部改为
经 McpClient 调远端 server，registry/ToolSpec 契约不变。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from polis.modules.model.gateway import ToolCall, ToolSpec


class McpToolNotFound(Exception):
    """注册表中无该工具名。"""


@dataclass
class McpTool:
    server: str
    name: str
    description: str
    parameters: dict[str, Any]  # JSON schema
    handler: Callable[[dict[str, Any]], str]


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
    """工具执行：按 ToolCall.name 路由到注册工具。桩为本地同步 handler；真实 MCP 为远端 IO。"""

    def __init__(self, registry: McpRegistry) -> None:
        self._registry = registry

    async def call(self, tool_call: ToolCall) -> str:
        tool = self._registry.get(tool_call.name)
        if tool is None:
            raise McpToolNotFound(tool_call.name)
        return tool.handler(tool_call.arguments)


# ── 内置本地工具（桩）──────────────────────────────────────────────────────────


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
