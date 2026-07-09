from __future__ import annotations

import argparse
import asyncio

import pytest
from scripts.mcp import external_smoke

from polis.modules.runtime.mcp_smoke import McpSmokeResult


def _args(**overrides: object) -> argparse.Namespace:
    values = {
        "server": "browser-pilot",
        "transport": "sse",
        "url": "http://tools.local/sse",
        "command": None,
        "arg": [],
        "env": "{}",
        "headers": "{}",
        "timeout_seconds": 5.0,
        "sse_read_timeout_seconds": None,
        "call_tool": None,
        "tool_args": "{}",
        "require_tool": None,
        "require_called_tool": None,
        "preview_chars": 500,
        "json_out": None,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def test_external_smoke_cli_fails_when_no_tools_discovered(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    async def fake_smoke(*_args: object, **_kwargs: object) -> McpSmokeResult:
        return McpSmokeResult(
            server="browser-pilot",
            transport="sse",
            tools=[],
            checked_at="2026-07-09T10:00:00+00:00",
        )

    monkeypatch.setattr(external_smoke, "run_external_mcp_smoke", fake_smoke)

    code = asyncio.run(external_smoke._run(_args()))

    assert code == 1
    assert "discovered no tools" in capsys.readouterr().out


def test_external_smoke_cli_honors_required_tool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_smoke(*_args: object, **_kwargs: object) -> McpSmokeResult:
        return McpSmokeResult(
            server="browser-pilot",
            transport="sse",
            tools=["web_search"],
            checked_at="2026-07-09T10:00:00+00:00",
        )

    monkeypatch.setattr(external_smoke, "run_external_mcp_smoke", fake_smoke)

    code = asyncio.run(external_smoke._run(_args(require_tool="web_search")))

    assert code == 0
