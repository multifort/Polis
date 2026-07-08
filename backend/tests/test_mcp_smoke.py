from __future__ import annotations

import asyncio

import pytest

from polis.modules.runtime import mcp_smoke
from polis.modules.runtime.mcp import McpServerConfig, McpTool


def test_external_mcp_smoke_discovers_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_discover(config: McpServerConfig) -> list[McpTool]:
        assert config.server == "browser-pilot"
        return [
            McpTool(
                server=config.server,
                name="web_search",
                description="Search",
                parameters={"type": "object"},
                handler=lambda _args: "unused",
            )
        ]

    monkeypatch.setattr(mcp_smoke, "discover_mcp_tools", fake_discover)

    result = asyncio.run(
        mcp_smoke.run_external_mcp_smoke(
            McpServerConfig(
                server="browser-pilot",
                transport="sse",
                url="http://tools.local/sse",
                headers={"Authorization": "Bearer handle"},
            )
        )
    )

    assert result.server == "browser-pilot"
    assert result.transport == "sse"
    assert result.discovered is True
    assert result.tools == ["web_search"]
    assert result.called_tool is None
    evidence = result.to_evidence()
    assert evidence["ok"] is True
    assert evidence["server"] == "browser-pilot"
    assert evidence["transport"] == "sse"
    assert evidence["discovered_tools"] == ["web_search"]
    assert "headers" not in evidence
    assert "env" not in evidence


def test_external_mcp_smoke_can_call_discovered_tool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_discover(config: McpServerConfig) -> list[McpTool]:
        return [
            McpTool(
                server=config.server,
                name="web_search",
                description="Search",
                parameters={"type": "object"},
                handler=lambda args: f"result:{args['q']}",
            )
        ]

    monkeypatch.setattr(mcp_smoke, "discover_mcp_tools", fake_discover)

    result = asyncio.run(
        mcp_smoke.run_external_mcp_smoke(
            McpServerConfig(
                server="browser-pilot",
                transport="streamable_http",
                url="http://tools.local/mcp",
            ),
            call_tool="web_search",
            tool_args={"q": "polis"},
            preview_chars=8,
        )
    )

    assert result.tools == ["web_search"]
    assert result.called_tool == "web_search"
    assert result.call_result_preview == "result:p"


def test_external_mcp_smoke_failure_evidence_is_credential_safe() -> None:
    result = mcp_smoke.failed_mcp_smoke_evidence(
        McpServerConfig(
            server="browser-pilot",
            transport="sse",
            url="http://tools.local/sse",
            headers={"Authorization": "Bearer handle"},
        ),
        "connection failed",
    )

    evidence = result.to_evidence()
    assert evidence["ok"] is False
    assert evidence["error"] == "connection failed"
    assert evidence["discovered_tools"] == []
    assert "headers" not in evidence
    assert "Bearer" not in str(evidence)
