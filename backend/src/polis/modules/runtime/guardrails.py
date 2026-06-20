"""Guardrails 安全防线（design 04 §5）。

威胁：抓来的外部内容里藏指令 → 操纵带工具+带凭证的 Agent。
- 防线1（本文件）：输入 Guardrails——工具输入注入检测 + 工具回流内容过滤。
- 防线2 最小权限：SkillLoader 按 allowed_tools 过滤（见 runtime/skills.py）。
- 防线3 危险动作 gate：node.dangerous → human 节点（见 planner/schemas.validate）。

M4 为规则版（ADR-0007）；M6 换 Guardrails-AI（注入检测/内容过滤/PII）。
"""

from __future__ import annotations

import json
import re

from polis.modules.model.gateway import ToolCall


class GuardrailViolation(Exception):
    """检测到注入/越权内容，阻断该工具调用。"""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


# 注入提示词模式（中英）。命中即视为可疑。
_INJECTION_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"ignore\s+(all\s+)?(previous|prior|above)\s+instructions",
        r"disregard\s+(the\s+)?(above|previous)",
        r"you\s+are\s+now\s+",
        r"system\s+prompt",
        r"reveal\s+.{0,20}(prompt|instructions|system)",
        r"忽略(以上|之前|前面|上述|所有).{0,8}(指令|提示|要求|规则)",
        r"无视(以上|之前|前面|上述).{0,8}(指令|提示|要求)",
        r"泄露.{0,10}(系统提示|提示词|指令)",
        r"<\|im_(start|end)\|>",
    )
]

_FILTERED = "[内容已过滤]"


def _find_injection(text: str) -> str | None:
    for pat in _INJECTION_PATTERNS:
        if pat.search(text):
            return pat.pattern
    return None


class Guardrails:
    """规则版防线1。无状态，可单例复用。"""

    def check_tool_input(self, tool_call: ToolCall) -> None:
        """工具输入注入检测：命中抛 GuardrailViolation（调用方阻断 + 审计 + 可选人审）。"""
        blob = json.dumps(tool_call.arguments, ensure_ascii=False)
        hit = _find_injection(blob)
        if hit is not None:
            raise GuardrailViolation(f"工具 {tool_call.name} 输入疑似提示注入：{hit}")

    def sanitize(self, output: str) -> str:
        """工具回流内容过滤：把注入片段替换为占位，阻止外部内容操纵后续推理。"""
        out = output
        for pat in _INJECTION_PATTERNS:
            out = pat.sub(_FILTERED, out)
        return out
