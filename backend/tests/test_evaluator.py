"""单元测试（M6-H）：Evaluator 断言 + LLM-judge（mock gateway）+ 回归。无 DB。"""

from __future__ import annotations

import asyncio

from polis.modules.model.gateway import ChatResponse, ResolvedModel, StubModelGateway
from polis.modules.observability import evaluator

_MODEL = ResolvedModel(id="m", provider="p", litellm_name="x", context_window=8192)


def test_assertions_empty_fails() -> None:
    r = asyncio.run(evaluator.score(StubModelGateway(), _MODEL, "   "))
    assert r.assertions_ok is False
    assert r.passed is False


def test_assertions_required_fields() -> None:
    r = asyncio.run(
        evaluator.score(
            StubModelGateway(), _MODEL, "含 单价 和 交期", expected_fields=["单价", "交期"]
        )
    )
    assert r.assertions_ok is True
    r2 = asyncio.run(
        evaluator.score(StubModelGateway(), _MODEL, "只含单价", expected_fields=["单价", "交期"])
    )
    assert r2.assertions_ok is False


def test_judge_pass_and_fail() -> None:
    # judge 返回高分 → passed
    gw_hi = StubModelGateway(script=[ChatResponse(content="0.9")])
    r = asyncio.run(
        evaluator.score(gw_hi, _MODEL, "一份完整报告", acceptance_criteria="是否为完整报告")
    )
    assert r.judge_score == 0.9
    assert r.passed is True

    # judge 返回低分 → not passed（即便断言过）
    gw_lo = StubModelGateway(script=[ChatResponse(content="0.3")])
    r2 = asyncio.run(evaluator.score(gw_lo, _MODEL, "残缺", acceptance_criteria="是否为完整报告"))
    assert r2.judge_score == 0.3
    assert r2.passed is False


def test_double_judge_only_rechecks_borderline_score_and_takes_lower() -> None:
    gw = StubModelGateway(script=[ChatResponse(content="0.65"), ChatResponse(content="0.55")])

    result = asyncio.run(
        evaluator.score(
            gw,
            _MODEL,
            "一份处于达标边缘的报告",
            acceptance_criteria="是否完整且有据",
            pass_threshold=0.6,
            double_judge=True,
            double_judge_margin=0.08,
        )
    )

    assert result.judge_score == 0.55
    assert result.passed is False
    assert result.detail["judge_scores"] == [0.65, 0.55]
    assert result.detail["judge_policy"] == "min_of_two"


def test_double_judge_keeps_clear_score_single() -> None:
    gw = StubModelGateway(script=[ChatResponse(content="0.9"), ChatResponse(content="0.1")])

    result = asyncio.run(
        evaluator.score(
            gw,
            _MODEL,
            "一份清晰达标的报告",
            acceptance_criteria="是否完整且有据",
            pass_threshold=0.6,
            double_judge=True,
            double_judge_margin=0.08,
        )
    )

    assert result.judge_score == 0.9
    assert result.passed is True
    assert result.detail["judge_scores"] == [0.9]
    assert result.detail["judge_policy"] == "single"


def test_double_judge_does_not_recheck_already_failing_score() -> None:
    gw = StubModelGateway(script=[ChatResponse(content="0.55"), ChatResponse(content="0.9")])

    result = asyncio.run(
        evaluator.score(
            gw,
            _MODEL,
            "一份未达标的报告",
            acceptance_criteria="是否完整且有据",
            pass_threshold=0.6,
            double_judge=True,
            double_judge_margin=0.08,
        )
    )

    assert result.judge_score == 0.55
    assert result.passed is False
    assert result.detail["judge_scores"] == [0.55]


def test_regression_set() -> None:
    gw = StubModelGateway(script=[ChatResponse(content="0.8"), ChatResponse(content="0.5")])
    cases = [
        {"output": "好报告", "acceptance_criteria": "完整性"},
        {"output": "差报告", "acceptance_criteria": "完整性"},
    ]
    results = asyncio.run(evaluator.regression(gw, _MODEL, cases))
    assert [r.judge_score for r in results] == [0.8, 0.5]
    assert [r.passed for r in results] == [True, False]
