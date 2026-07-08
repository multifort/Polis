"""External MCP server smoke runner.

Used by deployment checks to verify a configured stdio/SSE/Streamable HTTP MCP server can be
discovered via the standard SDK and, optionally, execute one tool.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from polis.modules.model.gateway import ToolCall
from polis.modules.runtime.mcp import (
    McpRegistry,
    McpRuntime,
    McpServerConfig,
    McpTool,
    discover_mcp_tools,
)


@dataclass(frozen=True)
class McpSmokeResult:
    server: str
    transport: str
    tools: list[str]
    called_tool: str | None = None
    call_result_preview: str | None = None
    ok: bool = True
    error: str | None = None
    checked_at: str = ""

    @property
    def discovered(self) -> bool:
        return bool(self.tools)

    def to_evidence(self) -> dict[str, Any]:
        """Return a credential-safe smoke evidence payload."""
        return {
            "ok": self.ok,
            "server": self.server,
            "transport": self.transport,
            "checked_at": self.checked_at,
            "discovered_tools": self.tools,
            "called_tool": self.called_tool,
            "call_result_preview": self.call_result_preview,
            "error": self.error,
        }


async def run_external_mcp_smoke(
    config: McpServerConfig,
    *,
    call_tool: str | None = None,
    tool_args: dict[str, Any] | None = None,
    preview_chars: int = 500,
) -> McpSmokeResult:
    """Discover tools from an external MCP server and optionally call one tool.

    The function intentionally returns only tool names and a bounded result preview. It does not
    echo headers/env to avoid leaking deployment credentials into logs.
    """
    tools = await discover_mcp_tools(config)
    registry = _registry_from_tools(tools)
    tool_names = sorted(tool.name for tool in tools if tool.name)
    if call_tool is None:
        return McpSmokeResult(
            server=config.server,
            transport=config.transport,
            tools=tool_names,
            checked_at=_now_iso(),
        )
    result = await McpRuntime(registry).call(
        ToolCall(id="external-mcp-smoke", name=call_tool, arguments=tool_args or {})
    )
    return McpSmokeResult(
        server=config.server,
        transport=config.transport,
        tools=tool_names,
        called_tool=call_tool,
        call_result_preview=result[:preview_chars],
        checked_at=_now_iso(),
    )


def _registry_from_tools(tools: list[McpTool]) -> McpRegistry:
    registry = McpRegistry()
    for tool in tools:
        if tool.name:
            registry.register(tool)
    return registry


def failed_mcp_smoke_evidence(config: McpServerConfig, error: str) -> McpSmokeResult:
    return McpSmokeResult(
        server=config.server,
        transport=config.transport,
        tools=[],
        ok=False,
        error=error,
        checked_at=_now_iso(),
    )


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()
