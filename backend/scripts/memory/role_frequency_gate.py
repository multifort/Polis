"""B3 task -> role -> org frequency-promotion live evidence gate.

The default scope excludes known benchmark/smoke organizations so a PASS represents
real business data. The JSON evidence deliberately omits memory content and org names.

Examples:
  uv run python scripts/memory/role_frequency_gate.py
  uv run python scripts/memory/role_frequency_gate.py --org-id <org_uuid>
  uv run python scripts/memory/role_frequency_gate.py \
    --json-out var/memory/b3-role-frequency.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select

from polis.db.session import get_sessionmaker, init_engine
from polis.modules.memory.models import Memory
from polis.modules.org.models import Org
from polis.modules.planner.models import TaskRun

_DEFAULT_MIN_FREQUENCY = 2
_MIN_CONFIDENCE = 0.7
_BENCHMARK_ORG_PREFIXES = ("M7验收门-",)
_BENCHMARK_ORG_NAMES = {
    "R4复用率样本公司",
    "R4自然复用Smoke公司",
    "B3频次门Smoke公司",
}


@dataclass(frozen=True)
class MemoryFact:
    memory_id: uuid.UUID
    org_id: uuid.UUID
    org_name: str | None
    content: str
    namespace: str
    confidence: float
    provenance: dict[str, Any] | None
    promoted_from: uuid.UUID | None


@dataclass(frozen=True)
class FactCheck:
    memory_id: uuid.UUID
    org_id: uuid.UUID
    declared_frequency: int | None
    observed_frequency: int
    source_task_count: int
    done_task_count: int
    role_namespaces: tuple[str, ...]
    errors: tuple[str, ...]

    @property
    def valid(self) -> bool:
        return not self.errors

    def to_json(self) -> dict[str, Any]:
        return {
            "memory_id": str(self.memory_id),
            "org_id": str(self.org_id),
            "declared_frequency": self.declared_frequency,
            "observed_frequency": self.observed_frequency,
            "source_task_count": self.source_task_count,
            "done_task_count": self.done_task_count,
            "role_namespaces": list(self.role_namespaces),
            "valid": self.valid,
            "errors": list(self.errors),
        }


@dataclass(frozen=True)
class GateSummary:
    min_frequency: int
    checks: tuple[FactCheck, ...]

    @property
    def has_data(self) -> bool:
        return bool(self.checks)

    @property
    def valid_count(self) -> int:
        return sum(check.valid for check in self.checks)

    @property
    def passed(self) -> bool:
        return self.has_data and self.valid_count == len(self.checks)

    @property
    def status(self) -> str:
        if not self.has_data:
            return "no_data"
        return "pass" if self.passed else "fail"

    def to_json(
        self,
        *,
        org_id: uuid.UUID | None,
        include_benchmark: bool,
    ) -> dict[str, Any]:
        return {
            "ok": self.passed,
            "status": self.status,
            "org_id": str(org_id) if org_id is not None else None,
            "include_benchmark": include_benchmark,
            "min_frequency": self.min_frequency,
            "candidate_count": len(self.checks),
            "valid_count": self.valid_count,
            "facts": [check.to_json() for check in self.checks],
        }


def is_benchmark_org_name(name: str | None) -> bool:
    if not name:
        return False
    return name in _BENCHMARK_ORG_NAMES or any(
        name.startswith(prefix) for prefix in _BENCHMARK_ORG_PREFIXES
    )


def _string_list(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(sorted({item for item in value if isinstance(item, str) and item}))


def _task_ids(fact: MemoryFact) -> set[str]:
    task_ids = set(_string_list((fact.provenance or {}).get("task_ids")))
    if fact.promoted_from is not None:
        task_ids.add(str(fact.promoted_from))
    return task_ids


def evaluate_gate(
    org_facts: list[MemoryFact],
    role_facts: list[MemoryFact],
    task_statuses: dict[tuple[uuid.UUID, str], str],
    *,
    min_frequency: int = _DEFAULT_MIN_FREQUENCY,
) -> GateSummary:
    checks: list[FactCheck] = []
    for org_fact in org_facts:
        provenance = org_fact.provenance or {}
        if provenance.get("kind") != "role_frequency":
            continue

        errors: list[str] = []
        raw_frequency = provenance.get("role_frequency")
        declared_frequency = (
            raw_frequency
            if isinstance(raw_frequency, int) and not isinstance(raw_frequency, bool)
            else None
        )
        if declared_frequency is None:
            errors.append("provenance.role_frequency must be an integer")
        elif declared_frequency < min_frequency:
            errors.append(f"declared frequency is below {min_frequency}")

        declared_namespaces = _string_list(provenance.get("role_namespaces"))
        if not declared_namespaces:
            errors.append("provenance.role_namespaces is empty")

        matching_roles = [
            fact
            for fact in role_facts
            if fact.org_id == org_fact.org_id and fact.content == org_fact.content
        ]
        observed_namespaces = tuple(sorted({fact.namespace for fact in matching_roles}))
        if not matching_roles:
            errors.append("matching role fact is missing")
        elif observed_namespaces != declared_namespaces:
            errors.append("role namespace evidence does not match provenance")

        source_task_ids: set[str] = set()
        for role_fact in matching_roles:
            role_task_ids = _task_ids(role_fact)
            source_task_ids.update(role_task_ids)
            occurrence_count = (role_fact.provenance or {}).get("occurrence_count")
            if occurrence_count != len(role_task_ids):
                errors.append(f"role occurrence_count mismatch for {role_fact.namespace}")
            if role_fact.confidence < _MIN_CONFIDENCE:
                errors.append(f"role confidence below {_MIN_CONFIDENCE} for {role_fact.namespace}")

        observed_frequency = len(source_task_ids)
        if declared_frequency is not None and observed_frequency != declared_frequency:
            errors.append("observed role task frequency does not match provenance")
        if observed_frequency < min_frequency:
            errors.append(f"observed role task frequency is below {min_frequency}")
        if org_fact.confidence < _MIN_CONFIDENCE:
            errors.append(f"org confidence is below {_MIN_CONFIDENCE}")

        promoted_from = str(org_fact.promoted_from) if org_fact.promoted_from is not None else None
        if promoted_from is None:
            errors.append("org promoted_from is missing")
        elif promoted_from not in source_task_ids:
            errors.append("org promoted_from is not present in role task evidence")

        done_task_count = sum(
            task_statuses.get((org_fact.org_id, task_id)) == "done" for task_id in source_task_ids
        )
        if done_task_count != observed_frequency:
            errors.append("one or more source tasks are missing, cross-org, or not done")

        checks.append(
            FactCheck(
                memory_id=org_fact.memory_id,
                org_id=org_fact.org_id,
                declared_frequency=declared_frequency,
                observed_frequency=observed_frequency,
                source_task_count=observed_frequency,
                done_task_count=done_task_count,
                role_namespaces=declared_namespaces,
                errors=tuple(dict.fromkeys(errors)),
            )
        )
    return GateSummary(min_frequency=min_frequency, checks=tuple(checks))


def _as_fact(memory: Memory, org_name: str | None) -> MemoryFact:
    return MemoryFact(
        memory_id=memory.id,
        org_id=memory.org_id,
        org_name=org_name,
        content=memory.content,
        namespace=memory.namespace,
        confidence=memory.confidence,
        provenance=memory.provenance,
        promoted_from=memory.promoted_from,
    )


async def _load_inputs(
    org_id: uuid.UUID | None,
    *,
    include_benchmark: bool,
) -> tuple[list[MemoryFact], list[MemoryFact], dict[tuple[uuid.UUID, str], str]]:
    init_engine()
    async with get_sessionmaker()() as session:
        org_query = (
            select(Memory, Org.name)
            .join(Org, Memory.org_id == Org.id)
            .where(Memory.scope == "org", Memory.namespace == "company")
        )
        if org_id is not None:
            org_query = org_query.where(Memory.org_id == org_id)

        org_facts = [
            _as_fact(memory, org_name)
            for memory, org_name in (await session.execute(org_query)).all()
            if include_benchmark or not is_benchmark_org_name(org_name)
        ]
        candidate_org_ids = {
            fact.org_id
            for fact in org_facts
            if (fact.provenance or {}).get("kind") == "role_frequency"
        }
        if not candidate_org_ids:
            return org_facts, [], {}

        role_rows = (
            await session.execute(
                select(Memory, Org.name)
                .join(Org, Memory.org_id == Org.id)
                .where(Memory.scope == "role", Memory.org_id.in_(candidate_org_ids))
            )
        ).all()
        role_facts = [_as_fact(memory, org_name) for memory, org_name in role_rows]

        task_uuids: set[uuid.UUID] = set()
        for fact in role_facts:
            for task_id in _task_ids(fact):
                try:
                    task_uuids.add(uuid.UUID(task_id))
                except ValueError:
                    continue

        task_statuses: dict[tuple[uuid.UUID, str], str] = {}
        if task_uuids:
            rows = (
                await session.execute(
                    select(TaskRun.id, TaskRun.org_id, TaskRun.status).where(
                        TaskRun.id.in_(task_uuids)
                    )
                )
            ).all()
            task_statuses = {(row.org_id, str(row.id)): row.status for row in rows}
        return org_facts, role_facts, task_statuses


def _write_json(path: str | None, payload: dict[str, Any]) -> None:
    if path is None:
        return
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


async def run(
    org_id: uuid.UUID | None,
    *,
    min_frequency: int,
    include_benchmark: bool,
    json_out: str | None,
) -> int:
    org_facts, role_facts, task_statuses = await _load_inputs(
        org_id,
        include_benchmark=include_benchmark,
    )
    summary = evaluate_gate(
        org_facts,
        role_facts,
        task_statuses,
        min_frequency=min_frequency,
    )
    _write_json(
        json_out,
        summary.to_json(org_id=org_id, include_benchmark=include_benchmark),
    )

    scope = f"org={org_id}" if org_id is not None else "all orgs"
    print(f"B3 role frequency gate: {scope}")
    print(f"benchmark/smoke org: {'included' if include_benchmark else 'excluded'}")
    print(f"minimum distinct done tasks: {min_frequency}")
    if not summary.has_data:
        print("gate: NO DATA (no real role_frequency org facts yet)")
        return 2

    for check in summary.checks:
        state = "PASS" if check.valid else "FAIL"
        print(
            f"{state} memory={check.memory_id} org={check.org_id} "
            f"frequency={check.observed_frequency} done={check.done_task_count}"
        )
        for error in check.errors:
            print(f"  - {error}")
    print(
        f"gate: {'PASS' if summary.passed else 'FAIL'} "
        f"({summary.valid_count}/{len(summary.checks)} facts valid)"
    )
    return 0 if summary.passed else 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Verify B3 role-frequency promotion evidence")
    parser.add_argument("--org-id", type=uuid.UUID, default=None, help="only inspect one org")
    parser.add_argument(
        "--min-frequency",
        type=int,
        default=_DEFAULT_MIN_FREQUENCY,
        help="minimum distinct done tasks, default 2",
    )
    parser.add_argument(
        "--include-benchmark",
        action="store_true",
        help="include known benchmark/smoke organizations",
    )
    parser.add_argument("--json-out", default=None, help="write credential-safe JSON evidence")
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    if args.min_frequency < 2:
        raise SystemExit("--min-frequency must be >= 2")
    raise SystemExit(
        asyncio.run(
            run(
                args.org_id,
                min_frequency=args.min_frequency,
                include_benchmark=args.include_benchmark,
                json_out=args.json_out,
            )
        )
    )


if __name__ == "__main__":
    main()
