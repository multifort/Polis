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


class McpSmokeEvidenceError(ValueError):
    """External MCP smoke evidence does not satisfy the deployment gate."""


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


def validate_mcp_smoke_evidence(
    evidence: dict[str, Any],
    *,
    expected_server: str | None = None,
    expected_transport: str | None = None,
    require_tool: str | None = None,
    require_called_tool: str | None = None,
) -> None:
    """Validate credential-safe external MCP smoke evidence.

    The gate intentionally requires both a successful smoke result and at least one discovered
    tool. A failed JSON payload is still useful for diagnosis, but it must not be accepted as
    deployment evidence.
    """
    _reject_secret_bearing_keys(evidence)
    if evidence.get("ok") is not True:
        raise McpSmokeEvidenceError("external MCP smoke did not pass")

    server = evidence.get("server")
    if expected_server is not None and server != expected_server:
        raise McpSmokeEvidenceError(
            f"external MCP smoke server mismatch: expected {expected_server}, got {server}"
        )

    transport = evidence.get("transport")
    if expected_transport is not None and transport != expected_transport:
        raise McpSmokeEvidenceError(
            f"external MCP smoke transport mismatch: expected {expected_transport}, got {transport}"
        )

    checked_at = evidence.get("checked_at")
    if not isinstance(checked_at, str) or not checked_at:
        raise McpSmokeEvidenceError("external MCP smoke evidence missing checked_at")
    try:
        datetime.fromisoformat(checked_at)
    except ValueError as exc:
        raise McpSmokeEvidenceError("external MCP smoke checked_at is not ISO-8601") from exc

    tools = evidence.get("discovered_tools")
    if not isinstance(tools, list) or not tools or not all(isinstance(t, str) for t in tools):
        raise McpSmokeEvidenceError("external MCP smoke discovered no tools")

    if require_tool is not None and require_tool not in tools:
        raise McpSmokeEvidenceError(f"external MCP smoke did not discover tool: {require_tool}")

    called_tool = evidence.get("called_tool")
    if require_called_tool is not None and called_tool != require_called_tool:
        raise McpSmokeEvidenceError(
            f"external MCP smoke did not call required tool: {require_called_tool}"
        )


def _reject_secret_bearing_keys(value: Any, *, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key).lower()
            if key_text in {"headers", "env", "authorization", "api_key", "token", "secret"}:
                raise McpSmokeEvidenceError(
                    f"external MCP smoke evidence contains credential-bearing key: {path}.{key}"
                )
            _reject_secret_bearing_keys(child, path=f"{path}.{key}")
        return
    if isinstance(value, list):
        for idx, child in enumerate(value):
            _reject_secret_bearing_keys(child, path=f"{path}[{idx}]")


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()
