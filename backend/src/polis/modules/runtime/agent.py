"""lite-agent 执行循环（design 04 §3）。

最小循环：Model ↔ [工具调用] 多轮，超 MAX_STEPS 标 soft_fail（交 03 有界重规划）。
M4-E 会在工具调用前后插入 Guardrails（check_tool_input / sanitize）。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from polis.modules.model.gateway import ChatMessage, ModelGateway
from polis.modules.runtime.context import ExecCtx
from polis.modules.runtime.mcp import McpRuntime

MAX_STEPS = 8


@dataclass
class LoopResult:
    ok: bool
    content: str | None = None
    soft_fail: bool = False
    steps: int = 0
    tool_calls_made: int = 0
    tool_outputs: list[str] = field(default_factory=list)


async def run_loop(
    gateway: ModelGateway,
    runtime: McpRuntime,
    agent_prompt: str,
    ctx: ExecCtx,
    *,
    max_steps: int = MAX_STEPS,
) -> LoopResult:
    """多轮 tool-calling 循环。模型返回工具调用→执行→回灌；返回纯文本则结束。"""
    system = agent_prompt
    if ctx.skills.system_append:
        system += "\n\n" + ctx.skills.system_append
    if ctx.goal:
        system += f"\n\n目标：{ctx.goal}"
    user = ctx.node.get("input_hint") or ""
    if ctx.memory_slice:
        user += "\n\n" + ctx.memory_slice

    msgs = [ChatMessage(role="system", content=system), ChatMessage(role="user", content=user)]
    specs = [b.spec for b in ctx.skills.tools]
    tool_calls_made = 0
    tool_outputs: list[str] = []

    for step in range(1, max_steps + 1):
        rsp = await gateway.chat(ctx.model, msgs, tools=specs, cred=ctx.cred)
        if not rsp.tool_calls:
            return LoopResult(
                ok=True,
                content=rsp.content,
                steps=step,
                tool_calls_made=tool_calls_made,
                tool_outputs=tool_outputs,
            )
        # 先回灌 assistant 的工具调用，再逐个执行并回灌结果
        msgs.append(
            ChatMessage(role="assistant", content=rsp.content or "", tool_calls=rsp.tool_calls)
        )
        for tc in rsp.tool_calls:
            out = await runtime.call(tc)
            tool_calls_made += 1
            tool_outputs.append(out)
            msgs.append(ChatMessage(role="tool", content=out, tool_call_id=tc.id))

    # 超步数 → 可重规划（soft_fail）
    return LoopResult(
        ok=False,
        soft_fail=True,
        steps=max_steps,
        tool_calls_made=tool_calls_made,
        tool_outputs=tool_outputs,
    )
