"""Run the fixed Evaluator regression set against the configured real judge model.

Evidence omits case outputs and acceptance criteria. Without a real model key the gate
returns NO DATA rather than treating the deterministic stub as production evidence.

Examples:
  uv run python scripts/eval/judge_regression_gate.py
  uv run python scripts/eval/judge_regression_gate.py --json-out var/eval/judge.json
  uv run python scripts/eval/judge_regression_gate.py --no-double-judge
"""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from polis.config import get_settings
from polis.db.session import get_sessionmaker, init_engine
from polis.modules.model.gateway import ModelGateway, ResolvedModel, resolve_model
from polis.modules.model.litellm_gateway import LiteLLMGateway
from polis.modules.observability import evaluator

CASES_PATH = Path(__file__).with_name("judge_cases.json")
_DEFAULT_ACCURACY_THRESHOLD = 0.8


@dataclass(frozen=True)
class JudgeCase:
    case_id: str
    output: str
    acceptance_criteria: str
    expected_fields: list[str] | None
    expected_pass: bool


@dataclass(frozen=True)
class CaseCheck:
    case_id: str
    expected_pass: bool
    actual_pass: bool
    assertions_ok: bool
    judge_score: float
    judge_scores: tuple[float, ...]
    judge_policy: str

    @property
    def correct(self) -> bool:
        return self.expected_pass == self.actual_pass

    def to_json(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "expected_pass": self.expected_pass,
            "actual_pass": self.actual_pass,
            "assertions_ok": self.assertions_ok,
            "judge_score": self.judge_score,
            "judge_scores": list(self.judge_scores),
            "judge_policy": self.judge_policy,
            "correct": self.correct,
        }


@dataclass(frozen=True)
class GateSummary:
    dataset_version: str
    model_id: str
    accuracy_threshold: float
    pass_threshold: float
    double_judge: bool
    double_judge_margin: float
    max_attempts: int
    checks: tuple[CaseCheck, ...]

    @property
    def correct_count(self) -> int:
        return sum(check.correct for check in self.checks)

    @property
    def accuracy(self) -> float:
        return self.correct_count / len(self.checks) if self.checks else 0.0

    @property
    def passed(self) -> bool:
        return bool(self.checks) and self.accuracy >= self.accuracy_threshold

    def to_json(self) -> dict[str, Any]:
        return {
            "ok": self.passed,
            "status": "pass" if self.passed else "fail",
            "dataset_version": self.dataset_version,
            "model_id": self.model_id,
            "accuracy_threshold": self.accuracy_threshold,
            "pass_threshold": self.pass_threshold,
            "double_judge": self.double_judge,
            "double_judge_margin": self.double_judge_margin,
            "max_attempts": self.max_attempts,
            "case_count": len(self.checks),
            "correct_count": self.correct_count,
            "accuracy": self.accuracy,
            "cases": [check.to_json() for check in self.checks],
        }


def load_cases(path: Path = CASES_PATH) -> tuple[str, list[JudgeCase]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not isinstance(raw.get("version"), str):
        raise ValueError("judge dataset must contain a string version")
    items = raw.get("cases")
    if not isinstance(items, list) or not items:
        raise ValueError("judge dataset must contain non-empty cases")

    cases: list[JudgeCase] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("each judge case must be an object")
        case_id = item.get("id")
        if not isinstance(case_id, str) or not case_id or case_id in seen:
            raise ValueError("judge case id must be non-empty and unique")
        output = item.get("output")
        criteria = item.get("acceptance_criteria")
        expected_pass = item.get("expected_pass")
        expected_fields = item.get("expected_fields")
        if not isinstance(output, str) or not isinstance(criteria, str):
            raise ValueError(f"judge case {case_id} must contain string output and criteria")
        if not isinstance(expected_pass, bool):
            raise ValueError(f"judge case {case_id} expected_pass must be boolean")
        if expected_fields is not None and (
            not isinstance(expected_fields, list)
            or not all(isinstance(field, str) for field in expected_fields)
        ):
            raise ValueError(f"judge case {case_id} expected_fields must be string list or null")
        seen.add(case_id)
        cases.append(
            JudgeCase(
                case_id=case_id,
                output=output,
                acceptance_criteria=criteria,
                expected_fields=expected_fields,
                expected_pass=expected_pass,
            )
        )
    return raw["version"], cases


def summarize(
    *,
    dataset_version: str,
    model_id: str,
    cases: list[JudgeCase],
    results: list[evaluator.EvalResult],
    accuracy_threshold: float,
    pass_threshold: float,
    double_judge: bool,
    double_judge_margin: float,
    max_attempts: int,
) -> GateSummary:
    if len(cases) != len(results):
        raise ValueError("judge result count does not match case count")
    checks = tuple(
        CaseCheck(
            case_id=case.case_id,
            expected_pass=case.expected_pass,
            actual_pass=result.passed,
            assertions_ok=result.assertions_ok,
            judge_score=result.judge_score,
            judge_scores=tuple(float(score) for score in result.detail["judge_scores"]),
            judge_policy=str(result.detail["judge_policy"]),
        )
        for case, result in zip(cases, results, strict=True)
    )
    return GateSummary(
        dataset_version=dataset_version,
        model_id=model_id,
        accuracy_threshold=accuracy_threshold,
        pass_threshold=pass_threshold,
        double_judge=double_judge,
        double_judge_margin=double_judge_margin,
        max_attempts=max_attempts,
        checks=checks,
    )


def _write_json(path: str | None, payload: dict[str, Any]) -> None:
    if path is None:
        return
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


async def _evaluate_cases(
    gateway: ModelGateway,
    model: ResolvedModel,
    cases: list[JudgeCase],
    *,
    pass_threshold: float,
    double_judge: bool,
    double_judge_margin: float,
    max_attempts: int,
) -> list[evaluator.EvalResult]:
    results: list[evaluator.EvalResult] = []
    for case in cases:
        last_error: Exception | None = None
        for attempt in range(1, max_attempts + 1):
            try:
                result = await evaluator.score(
                    gateway,
                    model,
                    case.output,
                    expected_fields=case.expected_fields,
                    acceptance_criteria=case.acceptance_criteria,
                    pass_threshold=pass_threshold,
                    double_judge=double_judge,
                    double_judge_margin=double_judge_margin,
                )
            except Exception as exc:  # noqa: BLE001 - gate retries provider/network failures
                last_error = exc
                if attempt < max_attempts:
                    await asyncio.sleep(min(attempt, 2))
                continue
            results.append(result)
            break
        else:
            assert last_error is not None
            raise last_error
    return results


async def run(
    *,
    cases_path: Path,
    accuracy_threshold: float,
    pass_threshold: float,
    double_judge: bool,
    double_judge_margin: float,
    max_attempts: int,
    json_out: str | None,
) -> int:
    settings = get_settings()
    if not settings.deepseek_api_key:
        payload = {
            "ok": False,
            "status": "no_data",
            "reason": "POLIS_DEEPSEEK_API_KEY is not configured",
        }
        _write_json(json_out, payload)
        print("Judge regression gate: NO DATA (real model key is not configured)")
        return 2

    try:
        dataset_version, cases = load_cases(cases_path)
        init_engine()
        async with get_sessionmaker()() as session:
            model = await resolve_model(session, settings.default_chat_model)
        results = await _evaluate_cases(
            LiteLLMGateway(),
            model,
            cases,
            pass_threshold=pass_threshold,
            double_judge=double_judge,
            double_judge_margin=double_judge_margin,
            max_attempts=max_attempts,
        )
    except Exception as exc:  # noqa: BLE001 - gate must emit concise credential-safe evidence
        payload = {
            "ok": False,
            "status": "fail",
            "reason": "model_or_dataset_error",
            "error_type": type(exc).__name__,
        }
        _write_json(json_out, payload)
        print(f"Judge regression gate: FAIL ({type(exc).__name__})")
        return 1
    summary = summarize(
        dataset_version=dataset_version,
        model_id=model.id,
        cases=cases,
        results=results,
        accuracy_threshold=accuracy_threshold,
        pass_threshold=pass_threshold,
        double_judge=double_judge,
        double_judge_margin=double_judge_margin,
        max_attempts=max_attempts,
    )
    _write_json(json_out, summary.to_json())

    print(
        f"Judge regression gate: dataset={dataset_version} model={model.id} "
        f"double_judge={double_judge}"
    )
    for check in summary.checks:
        state = "PASS" if check.correct else "FAIL"
        print(
            f"{state} {check.case_id}: expected={check.expected_pass} "
            f"actual={check.actual_pass} scores={list(check.judge_scores)}"
        )
    print(
        f"gate: {'PASS' if summary.passed else 'FAIL'} "
        f"accuracy={summary.correct_count}/{len(summary.checks)}={summary.accuracy:.0%} "
        f"target>={summary.accuracy_threshold:.0%}"
    )
    return 0 if summary.passed else 1


def _build_parser() -> argparse.ArgumentParser:
    settings = get_settings()
    parser = argparse.ArgumentParser(description="Run the fixed real-model judge regression set")
    parser.add_argument("--cases", type=Path, default=CASES_PATH)
    parser.add_argument(
        "--accuracy-threshold",
        type=float,
        default=_DEFAULT_ACCURACY_THRESHOLD,
    )
    parser.add_argument("--pass-threshold", type=float, default=settings.quality_gate_tau)
    parser.add_argument(
        "--double-judge",
        action=argparse.BooleanOptionalAction,
        default=settings.quality_gate_double_judge,
    )
    parser.add_argument(
        "--double-judge-margin",
        type=float,
        default=settings.quality_gate_double_judge_margin,
    )
    parser.add_argument("--attempts", type=int, default=2, help="provider attempts per case")
    parser.add_argument("--json-out", default=None)
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    for name, value in (
        ("accuracy threshold", args.accuracy_threshold),
        ("pass threshold", args.pass_threshold),
        ("double judge margin", args.double_judge_margin),
    ):
        if not 0.0 <= value <= 1.0:
            raise SystemExit(f"{name} must be between 0 and 1")
    if args.attempts < 1:
        raise SystemExit("attempts must be >= 1")
    raise SystemExit(
        asyncio.run(
            run(
                cases_path=args.cases,
                accuracy_threshold=args.accuracy_threshold,
                pass_threshold=args.pass_threshold,
                double_judge=args.double_judge,
                double_judge_margin=args.double_judge_margin,
                max_attempts=args.attempts,
                json_out=args.json_out,
            )
        )
    )


if __name__ == "__main__":
    main()
