"""单元测试（M4-C）：McpRegistry / McpRuntime 桩工具。纯逻辑，无 DB。"""

from __future__ import annotations

import asyncio

import pytest

from polis.modules.model.gateway import ToolCall
from polis.modules.runtime.mcp import McpRuntime, McpToolNotFound, default_registry


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
