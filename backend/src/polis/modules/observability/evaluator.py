"""Evaluator（design 06 §4）：客观断言 + LLM-judge 主观评分 + 回归集。

- assertions：格式/字段/非空（确定性）。
- llm_judge：用 ModelGateway 让模型判断是否满足验收标准（0~1 分）。
- regression：改 prompt/Agent 前后跑同一评测集对比，防"改了变差"。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from polis.modules.model.gateway import ChatMessage, ModelGateway, ResolvedModel

_PASS_THRESHOLD = 0.7


@dataclass
class EvalResult:
    passed: bool
    assertions_ok: bool
    judge_score: float
    detail: dict[str, Any] = field(default_factory=dict)


def _assertions(output: str, expected_fields: list[str] | None) -> bool:
    """客观断言：非空 + （若给定）包含全部期望字段/关键词。"""
    if not output or not output.strip():
        return False
    if expected_fields:
        return all(f in output for f in expected_fields)
    return True


def _parse_score(text: str | None) -> float:
    """从模型回复中解析 0~1 分数（容错：取第一个 0..1 浮点）。"""
    if not text:
        return 0.0
    m = re.search(r"\b(0(\.\d+)?|1(\.0+)?)\b", text)
    return float(m.group(1)) if m else 0.0


# 固定评分锚点（design §6.1 防糊弄：给维度 + 锚点，降 judge 方差，让分数可复现/稳定）
_JUDGE_SYSTEM = (
    "你是严格、稳定的评审。按以下**固定维度**给待评输出打分，再综合成一个 0~1 总分：\n"
    "① 切题：是否直接回应验收标准/目标（不跑题、不套模板空话）；\n"
    "② 完整：覆盖标准要求的关键要素；\n"
    "③ 可执行：有具体、量化、可落地的结论/建议（非泛泛而谈）；\n"
    "④ 有据：有数据/出处支撑，不臆造。\n"
    "评分锚点（务必据此，保证一致性）：0.9~1.0=四项都好；0.7~0.8=基本达标有小瑕；"
    "0.5~0.6=达标边缘、缺一项；0.3~0.4=明显不足；0~0.2=跑题/空洞。\n"
    "**只输出一个 0~1 之间两位小数，不要任何其他文字。**"
)


async def _llm_judge(
    gateway: ModelGateway, model: ResolvedModel, output: str, criteria: str
) -> float:
    msgs = [
        ChatMessage(role="system", content=_JUDGE_SYSTEM),
        ChatMessage(role="user", content=f"验收标准：{criteria}\n\n待评输出：\n{output}\n\n总分："),
    ]
    rsp = await gateway.chat(model, msgs)
    return _parse_score(rsp.content)


async def score(
    gateway: ModelGateway,
    model: ResolvedModel,
    output: str,
    *,
    expected_fields: list[str] | None = None,
    acceptance_criteria: str | None = None,
) -> EvalResult:
    """评一条产出：assertions(客观) + llm_judge(主观)。passed = 断言过 且 judge ≥ 0.7。"""
    a_ok = _assertions(output, expected_fields)
    judge = (
        await _llm_judge(gateway, model, output, acceptance_criteria)
        if acceptance_criteria
        else 1.0
    )
    return EvalResult(
        passed=a_ok and judge >= _PASS_THRESHOLD,
        assertions_ok=a_ok,
        judge_score=judge,
        detail={"expected_fields": expected_fields, "criteria": acceptance_criteria},
    )


async def regression(
    gateway: ModelGateway, model: ResolvedModel, cases: list[dict[str, Any]]
) -> list[EvalResult]:
    """回归集：对每个 case（output/acceptance_criteria/expected_fields）评分，供改动前后对比。"""
    results: list[EvalResult] = []
    for c in cases:
        results.append(
            await score(
                gateway,
                model,
                c.get("output", ""),
                expected_fields=c.get("expected_fields"),
                acceptance_criteria=c.get("acceptance_criteria"),
            )
        )
    return results
