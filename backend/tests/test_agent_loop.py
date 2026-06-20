"""单元测试（M4-D）：lite-agent _loop 多轮 tool-calling + 超步保护。纯逻辑，无 DB。"""

from __future__ import annotations

import asyncio

from polis.modules.model.credential import ScopedCredential
from polis.modules.model.gateway import (
    ChatResponse,
    ResolvedModel,
    StubModelGateway,
    ToolCall,
    ToolSpec,
)
from polis.modules.runtime.agent import run_loop
from polis.modules.runtime.context import ExecCtx
from polis.modules.runtime.mcp import McpRuntime, default_registry
from polis.modules.runtime.skills import BoundTool, LoadedSkills

_MODEL = ResolvedModel(id="stub", provider="stub", litellm_name=None, context_window=8192)


def _ctx() -> ExecCtx:
    echo = BoundTool(
        spec=ToolSpec(name="echo", description="回显", parameters={}),
        mcp_server="local",
        tool="echo",
    )
    return ExecCtx(
        goal="产出结论",
        memory_slice="",
        skills=LoadedSkills(system_append="", tools=[echo]),
        model=_MODEL,
        cred=ScopedCredential(handle="h", model_id="stub", task_id="t"),
        node={"input_hint": "分析供应商"},
    )


def test_loop_multi_turn_tool_then_finish() -> None:
    script = [
        ChatResponse(
            content=None, tool_calls=[ToolCall(id="c1", name="echo", arguments={"text": "hi"})]
        ),
        ChatResponse(content="结论已出"),
    ]
    res = asyncio.run(
        run_loop(StubModelGateway(script), McpRuntime(default_registry()), "你是分析师", _ctx())
    )
    assert res.ok is True
    assert res.content == "结论已出"
    assert res.tool_calls_made == 1
    assert res.tool_outputs == ["hi"]
    assert res.steps == 2


def test_loop_no_tool_returns_immediately() -> None:
    res = asyncio.run(run_loop(StubModelGateway(), McpRuntime(default_registry()), "p", _ctx()))
    assert res.ok is True
    assert res.tool_calls_made == 0
    assert (res.content or "").startswith("[stub]")


def test_loop_max_steps_soft_fail() -> None:
    # 模型每轮都要调工具 → 永不收敛 → 超步 soft_fail（可重规划）
    script = [
        ChatResponse(
            content=None, tool_calls=[ToolCall(id=f"c{i}", name="echo", arguments={"text": "x"})]
        )
        for i in range(10)
    ]
    res = asyncio.run(
        run_loop(StubModelGateway(script), McpRuntime(default_registry()), "p", _ctx(), max_steps=3)
    )
    assert res.ok is False
    assert res.soft_fail is True
    assert res.steps == 3
    assert res.tool_calls_made == 3
