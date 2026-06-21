"""ModelGateway：模型解析 + 推理抽象（design 04/06）。

M4 用 `StubModelGateway` 确定性桩（ADR-0007）：不调真实 LLM、不需 Key；
chat 可注入脚本化响应序列供 lite-agent 多轮 tool-calling 测试。
M6 换 `LiteLLMGateway`（同 `ModelGateway` 协议，调用方不变）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession

from polis.modules.model.models import ModelCatalog


class ModelNotFound(Exception):
    """model_catalog 中无该模型 id。"""


# ── 消息 / 工具 / 响应数据结构（与 LiteLLM/OpenAI tool-calling 同构）──────────────


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class ChatMessage:
    role: str  # system | user | assistant | tool
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str | None = None  # role=tool 时回指调用


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON schema


@dataclass
class ChatResponse:
    content: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)


@dataclass
class ResolvedModel:
    id: str
    provider: str | None
    litellm_name: str | None
    context_window: int | None


@runtime_checkable
class ModelGateway(Protocol):
    """推理网关协议。M4/M5 桩 / M6 LiteLLM 共用此契约。"""

    async def chat(
        self,
        model: ResolvedModel,
        messages: list[ChatMessage],
        tools: list[ToolSpec] | None = None,
        cred: Any | None = None,
    ) -> ChatResponse: ...

    async def embed(self, texts: list[str]) -> list[list[float] | None]:
        """文本向量化。返回与 texts 等长的向量列表（M5 桩可返回 None，待 M6）。"""
        ...


class StubModelGateway:
    """确定性桩（ADR-0007）。

    - 注入 `script`（ChatResponse 序列）时按调用顺序弹出 —— 供 _loop 多轮 tool-calling 测试；
      脚本耗尽后回落到默认行为。
    - 默认行为：回显最后一条 user 消息为 `[stub] …`，不发起工具调用（终止循环）。
    """

    def __init__(self, script: list[ChatResponse] | None = None) -> None:
        self._script: list[ChatResponse] = list(script or [])

    async def chat(
        self,
        model: ResolvedModel,
        messages: list[ChatMessage],
        tools: list[ToolSpec] | None = None,
        cred: Any | None = None,
    ) -> ChatResponse:
        if self._script:
            return self._script.pop(0)
        last_user = next((m for m in reversed(messages) if m.role == "user"), None)
        return ChatResponse(content=f"[stub] {last_user.content if last_user else ''}")

    async def embed(self, texts: list[str]) -> list[list[float] | None]:
        # 桩：不产生向量（M5 检索走确定性路径）；M6 LiteLLMGateway 返回真实 embedding
        return [None for _ in texts]


async def resolve_model(session: AsyncSession, model_id: str) -> ResolvedModel:
    """从 model_catalog 解析模型描述（不含密钥，design 06）。"""
    row = await session.get(ModelCatalog, model_id)
    if row is None:
        raise ModelNotFound(model_id)
    return ResolvedModel(
        id=row.id,
        provider=row.provider,
        litellm_name=row.litellm_name,
        context_window=row.context_window,
    )
