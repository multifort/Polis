"""lite-agent 执行循环（design 04 §3）。

最小循环：Model ↔ [工具调用] 多轮，超 MAX_STEPS 标 soft_fail（交 03 有界重规划）。
M4-E 会在工具调用前后插入 Guardrails（check_tool_input / sanitize）。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from polis.modules.model.gateway import ChatMessage, ModelGateway, ToolSpec
from polis.modules.runtime.context import ExecCtx
from polis.modules.runtime.guardrails import Guardrails, GuardrailViolation
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
    blocked: bool = False
    blocked_reason: str | None = None


async def run_loop(
    gateway: ModelGateway,
    runtime: McpRuntime,
    agent_prompt: str,
    ctx: ExecCtx,
    *,
    max_steps: int = MAX_STEPS,
    guard: Guardrails | None = None,
    extra_specs: list[ToolSpec] | None = None,
    ctx_budget: int | None = None,
    max_output_tokens: int | None = None,
) -> LoopResult:
    """多轮 tool-calling 循环。模型返回工具调用→执行→回灌；返回纯文本则结束。

    V2-B4 预算治理：`ctx_budget` 截**输入**上下文（按 input_hint>依赖摘要>记忆 优先级保留）；
    `max_output_tokens` 设**输出**上限（仅设上限、绝不截已生成内容），透传到每次 chat。
    """
    system = agent_prompt
    if ctx.skills.system_append:
        system += "\n\n" + ctx.skills.system_append
    if ctx.goal:
        system += f"\n\n目标：{ctx.goal}"
    user = ctx.node.get("input_hint") or ""
    if ctx.deps_brief:  # V2-B1：直接依赖的上游产出摘要，确定性注入（修 F3）
        user += "\n\n" + ctx.deps_brief
    if ctx.attachments_brief:  # P2b-2：任务附件清单，确定性注入（正文经 read_attachment 懒加载）
        user += "\n\n" + ctx.attachments_brief
    if ctx.memory_slice:
        user += "\n\n" + ctx.memory_slice
    # B4：输入上下文超预算 → 截断（token≈chars/2；input_hint 在前，优先保留）。绝不截输出。
    if ctx_budget is not None:
        cap_chars = max(0, ctx_budget * 2 - len(system))
        if len(user) > cap_chars:
            user = user[:cap_chars] + "\n…（上下文超预算，已按优先级截断）"

    msgs = [ChatMessage(role="system", content=system), ChatMessage(role="user", content=user)]
    specs = [b.spec for b in ctx.skills.tools] + (extra_specs or [])
    tool_calls_made = 0
    tool_outputs: list[str] = []

    for step in range(1, max_steps + 1):
        rsp = await gateway.chat(
            ctx.model, msgs, tools=specs, cred=ctx.cred, max_tokens=max_output_tokens
        )
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
            # 防线1：工具输入注入检测 → 命中则阻断该节点（由 execute 层审计 + 可选人审）
            if guard is not None:
                try:
                    guard.check_tool_input(tc)
                except GuardrailViolation as exc:
                    return LoopResult(
                        ok=False,
                        soft_fail=True,
                        blocked=True,
                        blocked_reason=exc.reason,
                        steps=step,
                        tool_calls_made=tool_calls_made,
                        tool_outputs=tool_outputs,
                    )
            out = await runtime.call(tc)
            # 防线1：工具回流内容过滤（外部内容操纵防护）
            if guard is not None:
                out = guard.sanitize(out)
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
