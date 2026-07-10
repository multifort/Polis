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
_DOUBLE_JUDGE_MARGIN = 0.08


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
_JUDGE_RUBRIC = (
    "按以下**固定维度**给待评输出打分，再综合成一个 0~1 总分：\n"
    "① 切题：是否直接回应验收标准/目标（不跑题、不套模板空话）；\n"
    "② 完整：覆盖标准要求的关键要素；\n"
    "③ 可执行：有具体、量化、可落地的结论/建议（非泛泛而谈）；\n"
    "④ 有据：有数据/出处支撑，不臆造。\n"
    "评分锚点（务必据此，保证一致性）：0.9~1.0=四项都好；0.7~0.8=基本达标有小瑕；"
    "0.5~0.6=达标边缘、缺一项；0.3~0.4=明显不足；0~0.2=跑题/空洞。\n"
    "**只输出一个 0~1 之间两位小数，不要任何其他文字。**"
)
_JUDGE_SYSTEM = "你是严格、稳定的主评审。" + _JUDGE_RUBRIC
_JUDGE_REVIEW_SYSTEM = (
    "你是独立复核评审。不要参考或猜测其他评审的分数，重点检查遗漏、无依据结论和表面完整。"
    + _JUDGE_RUBRIC
)


async def _llm_judge(
    gateway: ModelGateway,
    model: ResolvedModel,
    output: str,
    criteria: str,
    *,
    system_prompt: str = _JUDGE_SYSTEM,
) -> float:
    msgs = [
        ChatMessage(role="system", content=system_prompt),
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
    pass_threshold: float = _PASS_THRESHOLD,
    double_judge: bool = False,
    double_judge_margin: float = _DOUBLE_JUDGE_MARGIN,
) -> EvalResult:
    """评一条产出；临界分可触发独立复核并按设计取两者低分。"""
    if not 0.0 <= pass_threshold <= 1.0:
        raise ValueError("pass_threshold must be between 0 and 1")
    if not 0.0 <= double_judge_margin <= 1.0:
        raise ValueError("double_judge_margin must be between 0 and 1")

    a_ok = _assertions(output, expected_fields)
    judge_scores = [
        await _llm_judge(gateway, model, output, acceptance_criteria)
        if acceptance_criteria
        else 1.0
    ]
    if (
        acceptance_criteria
        and double_judge
        and pass_threshold <= judge_scores[0] <= pass_threshold + double_judge_margin
    ):
        judge_scores.append(
            await _llm_judge(
                gateway,
                model,
                output,
                acceptance_criteria,
                system_prompt=_JUDGE_REVIEW_SYSTEM,
            )
        )
    judge = min(judge_scores)
    return EvalResult(
        passed=a_ok and judge >= pass_threshold,
        assertions_ok=a_ok,
        judge_score=judge,
        detail={
            "expected_fields": expected_fields,
            "criteria": acceptance_criteria,
            "judge_scores": judge_scores,
            "judge_policy": "min_of_two" if len(judge_scores) == 2 else "single",
            "pass_threshold": pass_threshold,
        },
    )


async def regression(
    gateway: ModelGateway,
    model: ResolvedModel,
    cases: list[dict[str, Any]],
    *,
    pass_threshold: float = _PASS_THRESHOLD,
    double_judge: bool = False,
    double_judge_margin: float = _DOUBLE_JUDGE_MARGIN,
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
                pass_threshold=pass_threshold,
                double_judge=double_judge,
                double_judge_margin=double_judge_margin,
            )
        )
    return results
