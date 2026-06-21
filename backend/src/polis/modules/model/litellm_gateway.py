"""LiteLLMGateway（design 06 §1）：经 LiteLLM 真调多家模型，实现 ModelGateway 协议。

chat → DeepSeek（api_key 优先短时凭证 cred.value，否则系统级 env）；embed → 本地 TEI(bge)。
M6-C。与 StubModelGateway 同协议，AgentRuntime 注入哪个即用哪个。
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from polis.config import get_settings
from polis.modules.model import repository as repo
from polis.modules.model.gateway import (
    ChatMessage,
    ChatResponse,
    ResolvedModel,
    ToolCall,
    ToolSpec,
)


def _msg_to_dict(m: ChatMessage) -> dict[str, Any]:
    d: dict[str, Any] = {"role": m.role, "content": m.content}
    if m.tool_calls:
        d["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)},
            }
            for tc in m.tool_calls
        ]
    if m.tool_call_id:
        d["tool_call_id"] = m.tool_call_id
    return d


def _tool_to_dict(t: ToolSpec) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {"name": t.name, "description": t.description, "parameters": t.parameters},
    }


class LiteLLMGateway:
    """真实推理网关（M6）。"""

    async def chat(
        self,
        model: ResolvedModel,
        messages: list[ChatMessage],
        tools: list[ToolSpec] | None = None,
        cred: Any | None = None,
    ) -> ChatResponse:
        import litellm

        settings = get_settings()
        api_key = (cred.value if cred is not None and cred.value else None) or (
            settings.deepseek_api_key or None
        )
        resp = await litellm.acompletion(
            model=model.litellm_name,
            messages=[_msg_to_dict(m) for m in messages],
            tools=[_tool_to_dict(t) for t in tools] if tools else None,
            api_key=api_key,
            api_base=settings.deepseek_base_url or None,
        )
        msg = resp.choices[0].message
        tool_calls = [
            ToolCall(
                id=tc.id,
                name=tc.function.name,
                arguments=json.loads(tc.function.arguments or "{}"),
            )
            for tc in (getattr(msg, "tool_calls", None) or [])
        ]
        return ChatResponse(content=msg.content, tool_calls=tool_calls)

    async def embed(self, texts: list[str]) -> list[list[float] | None]:
        import litellm

        settings = get_settings()
        resp = await litellm.aembedding(
            model="openai/bge-large-zh-v1.5",  # 本地 TEI，OpenAI 兼容端点，1024 维
            input=texts,
            api_base=f"{settings.embedding_base_url}/v1",
            api_key="not-needed",  # TEI 不校验
        )
        return [item["embedding"] for item in resp.data]


async def cost_aware_pick(session: AsyncSession, capability: str) -> ResolvedModel | None:
    """成本路由（design 06 §1.1，T6.2）：在具备某能力的模型中选最便宜的（够用选便宜）。"""
    rows = await repo.models_by_capability(session, capability)
    if not rows:
        return None
    pick = min(rows, key=lambda m: float(m.price_in or 0) + float(m.price_out or 0))
    return ResolvedModel(
        id=pick.id,
        provider=pick.provider,
        litellm_name=pick.litellm_name,
        context_window=pick.context_window,
    )
