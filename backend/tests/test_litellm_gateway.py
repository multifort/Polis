"""单元测试（M6-C）：LiteLLMGateway 消息/响应转换 + 协议一致性。mock litellm，无网络。"""

from __future__ import annotations

import asyncio
import sys
import types
from typing import Any

from polis.modules.model.gateway import (
    ChatMessage,
    ModelGateway,
    ResolvedModel,
    ToolSpec,
)
from polis.modules.model.litellm_gateway import LiteLLMGateway, _msg_to_dict, _tool_to_dict

_MODEL = ResolvedModel(
    id="deepseek-v4-pro",
    provider="deepseek",
    litellm_name="deepseek/deepseek-v4-pro",
    context_window=65536,
)


def test_protocol_conformance() -> None:
    assert isinstance(LiteLLMGateway(), ModelGateway)  # runtime_checkable


def test_msg_and_tool_serialization() -> None:
    from polis.modules.model.gateway import ToolCall

    asst = ChatMessage(
        role="assistant",
        content="",
        tool_calls=[ToolCall(id="c1", name="echo", arguments={"x": 1})],
    )
    d = _msg_to_dict(asst)
    assert d["tool_calls"][0]["function"]["name"] == "echo"
    assert d["tool_calls"][0]["function"]["arguments"] == '{"x": 1}'

    tool_msg = _msg_to_dict(ChatMessage(role="tool", content="out", tool_call_id="c1"))
    assert tool_msg["tool_call_id"] == "c1"

    spec = _tool_to_dict(ToolSpec(name="echo", description="d", parameters={"type": "object"}))
    assert spec["type"] == "function" and spec["function"]["name"] == "echo"


def _install_fake_litellm(message: Any) -> None:
    """注入假 litellm 模块，acompletion 返回给定 message。"""
    fake = types.ModuleType("litellm")
    fake.success_callback = []  # type: ignore[attr-defined]  _ensure_langfuse 会读/写它

    async def _acompletion(**kwargs: Any) -> Any:
        choice = types.SimpleNamespace(message=message)
        return types.SimpleNamespace(choices=[choice])

    fake.acompletion = _acompletion  # type: ignore[attr-defined]
    sys.modules["litellm"] = fake


def test_chat_parses_text_response() -> None:
    msg = types.SimpleNamespace(content="分析完成", tool_calls=None)
    _install_fake_litellm(msg)
    try:
        rsp = asyncio.run(LiteLLMGateway().chat(_MODEL, [ChatMessage(role="user", content="分析")]))
        assert rsp.content == "分析完成"
        assert rsp.tool_calls == []
    finally:
        del sys.modules["litellm"]


def test_chat_parses_tool_calls() -> None:
    tc = types.SimpleNamespace(
        id="c1", function=types.SimpleNamespace(name="echo", arguments='{"text": "hi"}')
    )
    msg = types.SimpleNamespace(content=None, tool_calls=[tc])
    _install_fake_litellm(msg)
    try:
        rsp = asyncio.run(
            LiteLLMGateway().chat(
                _MODEL,
                [ChatMessage(role="user", content="q")],
                tools=[ToolSpec(name="echo", description="d", parameters={})],
            )
        )
        assert len(rsp.tool_calls) == 1
        assert rsp.tool_calls[0].name == "echo"
        assert rsp.tool_calls[0].arguments == {"text": "hi"}
    finally:
        del sys.modules["litellm"]
