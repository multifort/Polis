"""Guardrails 安全防线（design 04 §5）。

威胁：抓来的外部内容里藏指令 → 操纵带工具+带凭证的 Agent。
- 防线1（本文件）：输入 Guardrails——工具输入注入检测 + 工具回流内容过滤。
- 防线2 最小权限：SkillLoader 按 allowed_tools 过滤（见 runtime/skills.py）。
- 防线3 危险动作 gate：node.dangerous → human 节点（见 planner/schemas.validate）。

M4 为规则版（ADR-0007）；M6 逐步补齐 PII 脱敏，完整 Guardrails-AI 留后续。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Protocol

from polis.config import get_settings
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
        r"developer\s+(message|instructions?)",
        r"(BEGIN|END)\s+(SYSTEM|DEVELOPER)\s+(PROMPT|MESSAGE|INSTRUCTIONS?)",
        r"act\s+as\s+(a\s+)?(system|developer|admin)",
        r"reveal\s+.{0,20}(prompt|instructions|system)",
        r"(print|dump|show|exfiltrate)\s+.{0,24}(secrets?|tokens?|credentials?|api\s*keys?)",
        r"<\s*(system|developer|assistant|tool)\s*>",
        r"忽略(以上|之前|前面|上述|所有).{0,8}(指令|提示|要求|规则)",
        r"无视(以上|之前|前面|上述).{0,8}(指令|提示|要求)",
        r"泄露.{0,10}(系统提示|提示词|指令)",
        r"(输出|打印|展示|泄露).{0,12}(密钥|令牌|凭证|api\s*key)",
        r"<\|im_(start|end)\|>",
    )
]

_FILTERED = "[内容已过滤]"
_PII_REDACTED = "[敏感信息已脱敏]"

# 常见 PII/凭证片段：仅用于工具回流内容脱敏，避免外部内容把敏感信息注入后续推理。
_PII_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b",
        r"(?<!\d)1[3-9]\d{9}(?!\d)",
        r"(?<!\d)\d{17}[\dXx](?!\d)",
        r"\b(?:sk|pk|rk|ak)-[A-Za-z0-9_-]{16,}\b",
        r"\bAKIA[0-9A-Z]{16}\b",
        r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b",
        r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b",
        r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b",
        r"\bBearer\s+[A-Za-z0-9._~+/=-]{16,}\b",
        r"\b[A-Za-z0-9_]*(?:api[_-]?key|token|secret)[A-Za-z0-9_]*\s*[:=]\s*['\"]?[^'\"\s,;]{8,}",
    )
]


@dataclass(frozen=True)
class GuardrailSanitizeReport:
    output: str
    injection_matches: int = 0
    pii_matches: int = 0
    categories: dict[str, int] = field(default_factory=dict)

    @property
    def changed(self) -> bool:
        return self.injection_matches > 0 or self.pii_matches > 0


class GuardrailProvider(Protocol):
    name: str

    def check_tool_input(self, tool_call: ToolCall) -> None: ...

    def sanitize_with_report(self, output: str) -> GuardrailSanitizeReport: ...


def _find_injection(text: str) -> str | None:
    for pat in _INJECTION_PATTERNS:
        if pat.search(text):
            return pat.pattern
    return None


class RulesGuardrailProvider:
    """规则版防线1。无状态，可单例复用。"""

    name = "rules"

    def check_tool_input(self, tool_call: ToolCall) -> None:
        """工具输入注入检测：命中抛 GuardrailViolation（调用方阻断 + 审计 + 可选人审）。"""
        blob = json.dumps(tool_call.arguments, ensure_ascii=False)
        hit = _find_injection(blob)
        if hit is not None:
            raise GuardrailViolation(f"工具 {tool_call.name} 输入疑似提示注入：{hit}")

    def sanitize_with_report(self, output: str) -> GuardrailSanitizeReport:
        """工具回流内容过滤，并返回命中计数，供审计/观测使用。"""
        out = output
        injection_matches = 0
        pii_matches = 0
        categories: dict[str, int] = {}
        for pat in _INJECTION_PATTERNS:
            out, count = pat.subn(_FILTERED, out)
            if count:
                injection_matches += count
                categories["injection"] = categories.get("injection", 0) + count
        for pat in _PII_PATTERNS:
            out, count = pat.subn(_PII_REDACTED, out)
            if count:
                pii_matches += count
                categories["pii_or_secret"] = categories.get("pii_or_secret", 0) + count
        return GuardrailSanitizeReport(
            output=out,
            injection_matches=injection_matches,
            pii_matches=pii_matches,
            categories=categories,
        )


class Guardrails:
    """Guardrails facade.

    默认走规则 provider；后续 Guardrails-AI adapter 可作为 primary provider 替换，或作为 shadow
    provider 对照命中率。Facade 保持 agent loop 调用契约稳定。
    """

    def __init__(
        self,
        provider: GuardrailProvider | None = None,
        *,
        shadow_provider: GuardrailProvider | None = None,
    ) -> None:
        self._provider = provider or RulesGuardrailProvider()
        self._shadow_provider = shadow_provider

    @classmethod
    def from_settings(cls) -> Guardrails:
        """按配置创建 Guardrails；默认 rules，Guardrails-AI 未安装时 fail-closed。"""
        settings = get_settings()
        provider = settings.guardrails_provider.lower()
        if provider == "rules":
            return cls()
        if provider == "guardrails_ai":
            raise RuntimeError(
                "POLIS_GUARDRAILS_PROVIDER=guardrails_ai 已启用，但 Guardrails-AI adapter "
                "尚未配置；请保持 rules 或安装/接入 adapter 后再启用。"
            )
        raise RuntimeError(f"不支持的 POLIS_GUARDRAILS_PROVIDER：{settings.guardrails_provider}")

    @property
    def provider_name(self) -> str:
        if self._shadow_provider is None:
            return self._provider.name
        return f"{self._provider.name}+shadow:{self._shadow_provider.name}"

    def check_tool_input(self, tool_call: ToolCall) -> None:
        """工具输入注入检测：命中抛 GuardrailViolation（调用方阻断 + 审计 + 可选人审）。"""
        self._provider.check_tool_input(tool_call)
        if self._shadow_provider is not None:
            self._shadow_provider.check_tool_input(tool_call)

    def sanitize(self, output: str) -> str:
        """工具回流内容过滤：过滤注入片段并脱敏常见 PII/凭证。"""
        return self.sanitize_with_report(output).output

    def sanitize_with_report(self, output: str) -> GuardrailSanitizeReport:
        """工具回流内容过滤，并返回命中计数，供审计/观测使用。"""
        report = self._provider.sanitize_with_report(output)
        if self._shadow_provider is None:
            return report
        shadow = self._shadow_provider.sanitize_with_report(output)
        categories = dict(report.categories)
        for category, count in shadow.categories.items():
            categories[f"shadow.{self._shadow_provider.name}.{category}"] = count
        return GuardrailSanitizeReport(
            output=report.output,
            injection_matches=report.injection_matches,
            pii_matches=report.pii_matches,
            categories=categories,
        )
