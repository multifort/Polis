"""Fixed judge regression gate tests."""

from __future__ import annotations

import asyncio
import os
from typing import Any

from scripts.eval.judge_regression_gate import (
    CASES_PATH,
    _evaluate_cases,
    _without_proxy_env,
    load_cases,
    summarize,
)

from polis.modules.model.gateway import ChatResponse, ResolvedModel, StubModelGateway
from polis.modules.observability.evaluator import EvalResult

_MODEL = ResolvedModel(id="m", provider="p", litellm_name="x", context_window=8192)


class _FlakyGateway(StubModelGateway):
    def __init__(self) -> None:
        super().__init__([ChatResponse(content="0.9")])
        self.calls = 0

    async def chat(self, *args: Any, **kwargs: Any) -> ChatResponse:
        self.calls += 1
        if self.calls == 1:
            raise ConnectionError("transient")
        return await super().chat(*args, **kwargs)


def _result(passed: bool, score: float) -> EvalResult:
    return EvalResult(
        passed=passed,
        assertions_ok=True,
        judge_score=score,
        detail={"judge_scores": [score], "judge_policy": "single"},
    )


def test_fixed_judge_cases_are_valid_and_balanced() -> None:
    version, cases = load_cases(CASES_PATH)

    assert version == "2026-07-10"
    assert len(cases) == 6
    assert sum(case.expected_pass for case in cases) == 3
    assert len({case.case_id for case in cases}) == len(cases)


def test_judge_summary_applies_accuracy_gate_without_leaking_case_text() -> None:
    version, cases = load_cases(CASES_PATH)
    results = [_result(case.expected_pass, 0.9 if case.expected_pass else 0.2) for case in cases]
    results[-1] = _result(True, 0.9)

    summary = summarize(
        dataset_version=version,
        model_id="judge-model",
        cases=cases,
        results=results,
        accuracy_threshold=0.8,
        pass_threshold=0.6,
        double_judge=True,
        double_judge_margin=0.08,
        max_attempts=2,
        proxy_disabled=False,
    )

    assert summary.correct_count == 5
    assert summary.accuracy == 5 / 6
    assert summary.passed is True
    payload = summary.to_json()
    assert "output" not in str(payload)
    assert "acceptance_criteria" not in str(payload)
    assert payload["proxy_disabled"] is False


def test_disable_proxy_context_removes_and_restores_standard_variables(
    monkeypatch: Any,
) -> None:
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.example")
    monkeypatch.setenv("https_proxy", "http://proxy.example")

    with _without_proxy_env(True):
        assert "HTTP_PROXY" not in os.environ
        assert "https_proxy" not in os.environ

    assert os.environ["HTTP_PROXY"] == "http://proxy.example"
    assert os.environ["https_proxy"] == "http://proxy.example"

    with _without_proxy_env(False):
        assert os.environ["HTTP_PROXY"] == "http://proxy.example"


def test_judge_gate_retries_transient_provider_failure() -> None:
    _, cases = load_cases(CASES_PATH)
    gateway = _FlakyGateway()

    results = asyncio.run(
        _evaluate_cases(
            gateway,
            _MODEL,
            cases[:1],
            pass_threshold=0.6,
            double_judge=False,
            double_judge_margin=0.08,
            max_attempts=2,
        )
    )

    assert gateway.calls == 2
    assert results[0].judge_score == 0.9
