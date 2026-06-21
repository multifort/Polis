"""单元测试（M4-A）：StubModelGateway 桩行为。纯逻辑，无 DB。"""

from __future__ import annotations

import asyncio

from polis.modules.model.gateway import (
    ChatMessage,
    ChatResponse,
    ResolvedModel,
    StubModelGateway,
    ToolCall,
)

_MODEL = ResolvedModel(id="stub", provider="stub", litellm_name=None, context_window=8192)


def test_stub_default_echoes_last_user() -> None:
    gw = StubModelGateway()
    msgs = [ChatMessage(role="system", content="sys"), ChatMessage(role="user", content="你好")]
    rsp = asyncio.run(gw.chat(_MODEL, msgs))
    assert rsp.tool_calls == []
    assert rsp.content == "[stub] 你好"


def test_stub_script_drives_multi_turn() -> None:
    # 第一轮返回 tool_call，第二轮返回最终文本 —— 模拟多轮 tool-calling
    script = [
        ChatResponse(content=None, tool_calls=[ToolCall(id="c1", name="echo", arguments={"x": 1})]),
        ChatResponse(content="完成"),
    ]
    gw = StubModelGateway(script=script)
    r1 = asyncio.run(gw.chat(_MODEL, [ChatMessage(role="user", content="q")]))
    assert r1.tool_calls and r1.tool_calls[0].name == "echo"
    r2 = asyncio.run(gw.chat(_MODEL, [ChatMessage(role="user", content="q")]))
    assert r2.content == "完成" and r2.tool_calls == []


def test_stub_falls_back_after_script_exhausted() -> None:
    gw = StubModelGateway(script=[ChatResponse(content="只有一条")])
    asyncio.run(gw.chat(_MODEL, [ChatMessage(role="user", content="a")]))
    # 脚本耗尽后回落默认
    rsp = asyncio.run(gw.chat(_MODEL, [ChatMessage(role="user", content="b")]))
    assert rsp.content == "[stub] b"


def test_stub_embed_returns_none_per_text() -> None:
    gw = StubModelGateway()
    out = asyncio.run(gw.embed(["a", "b", "c"]))
    assert out == [None, None, None]  # 桩无向量，待 M6
