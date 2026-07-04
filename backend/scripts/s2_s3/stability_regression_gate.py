"""S2b/S3 stability regression gate.

Runs the local deterministic regression suites that prove:
  - S2b local replan control flow and generated replacement sub-DAG validation.
  - S3 admission queue and priority dequeue behavior.

Usage:
  uv run python scripts/s2_s3/stability_regression_gate.py
  uv run python scripts/s2_s3/stability_regression_gate.py --skip-docker
  uv run python scripts/s2_s3/stability_regression_gate.py --keep-going
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Suite:
    name: str
    targets: tuple[str, ...]
    description: str
    requires_docker: bool = False


SUITES = (
    Suite(
        name="S2b workflow local replan",
        targets=("tests/test_workflow.py",),
        description="Workflow replacement, online generation activity, auto strategy, rework.",
    ),
    Suite(
        name="S2b generated sub-DAG",
        targets=("tests/test_plan_generator.py",),
        description="generate_subdag structure/semantic validation and bounded repair.",
    ),
    Suite(
        name="S3 concurrency queue",
        targets=("tests/test_integration_concurrency.py",),
        description="Admission queue, pending dequeue, multi-slot short-job-first ordering.",
        requires_docker=True,
    ),
)


@dataclass(frozen=True)
class SuiteResult:
    suite: Suite
    code: int
    elapsed: float

    @property
    def passed(self) -> bool:
        return self.code == 0


def _run_suite(suite: Suite, pytest_args: list[str]) -> SuiteResult:
    cmd = [sys.executable, "-m", "pytest", "-q", *suite.targets, *pytest_args]
    print(f"\n== {suite.name} ==", flush=True)
    print(suite.description, flush=True)
    print("$ " + " ".join(cmd), flush=True)
    start = time.monotonic()
    completed = subprocess.run(cmd, cwd=BACKEND_ROOT, check=False)  # noqa: S603
    elapsed = time.monotonic() - start
    return SuiteResult(suite=suite, code=completed.returncode, elapsed=elapsed)


def _select_suites(skip_docker: bool) -> list[Suite]:
    if not skip_docker:
        return list(SUITES)
    return [suite for suite in SUITES if not suite.requires_docker]


def run(*, skip_docker: bool, keep_going: bool, pytest_args: list[str]) -> int:
    selected = _select_suites(skip_docker)
    if not selected:
        print("No suites selected.")
        return 2

    if skip_docker:
        print("S2b/S3 stability regression gate: docker-backed suites skipped.", flush=True)
    else:
        print("S2b/S3 stability regression gate: full local suite.", flush=True)
    print(f"Suites: {len(selected)}", flush=True)

    results: list[SuiteResult] = []
    for suite in selected:
        result = _run_suite(suite, pytest_args)
        results.append(result)
        if not result.passed and not keep_going:
            break

    print("\n-- Summary --")
    for result in results:
        status = "PASS" if result.passed else "FAIL"
        print(f"{status:>4}  {result.elapsed:6.1f}s  {result.suite.name}")

    skipped = [suite for suite in SUITES if suite not in selected]
    for suite in skipped:
        print(f"SKIP          {suite.name}")

    failed = [result for result in results if not result.passed]
    if failed:
        print("\nGate: FAIL")
        return 1
    print("\nGate: PASS")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--skip-docker",
        action="store_true",
        help="Skip docker/testcontainers-backed S3 integration suite.",
    )
    parser.add_argument(
        "--keep-going",
        action="store_true",
        help="Run all selected suites even if an earlier suite fails.",
    )
    parser.add_argument(
        "pytest_args",
        nargs=argparse.REMAINDER,
        help="Extra pytest args after '--', for example: -- -k local_replan",
    )
    args = parser.parse_args()
    pytest_args = args.pytest_args
    if pytest_args[:1] == ["--"]:
        pytest_args = pytest_args[1:]
    raise SystemExit(
        run(skip_docker=args.skip_docker, keep_going=args.keep_going, pytest_args=pytest_args)
    )


if __name__ == "__main__":
    main()
