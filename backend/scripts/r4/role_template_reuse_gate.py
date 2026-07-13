"""R4 角色模板自动沉淀复用率验证门。

统计 live DB 中 generated role_template 对应的 Agent 是否在后续运行 manifest 中被复用。
口径：
  - 分母：status=active 且 source=generated 的 role_template
  - 分子：该模板同名 Agent 在 run_manifest.agents_used 中出现次数 >= --min-occurrences
  - 默认排除 M7 验收门 / R4 smoke 等 benchmark org；真实业务口径需要避免测试数据污染

默认 --min-occurrences=2：第一次出现通常是沉淀来源/首次使用，第二次及以后才算“后续复用”。

用法：
  uv run python scripts/r4/role_template_reuse_gate.py
  uv run python scripts/r4/role_template_reuse_gate.py --include-benchmark
  uv run python scripts/r4/role_template_reuse_gate.py --include-samples
  uv run python scripts/r4/role_template_reuse_gate.py --org-id <org_uuid> --threshold 0.6
  uv run python scripts/r4/role_template_reuse_gate.py --json-out var/r4/reuse.json
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
from polis.modules.observability.models import RunManifest
from polis.modules.org.models import Org, RoleTemplate

BENCHMARK_ORG_PREFIXES = ("M7验收门-",)
BENCHMARK_ORG_NAMES = {"R4复用率样本公司", "R4自然复用Smoke公司"}


@dataclass(frozen=True)
class RoleTemplateKey:
    org_id: uuid.UUID | None
    name: str


@dataclass(frozen=True)
class ReuseSummary:
    total: int
    reused: int
    threshold: float
    min_occurrences: int
    occurrences: dict[RoleTemplateKey, int]

    @property
    def rate(self) -> float:
        return self.reused / self.total if self.total else 0.0

    @property
    def has_data(self) -> bool:
        return self.total > 0

    @property
    def passed(self) -> bool:
        return self.has_data and self.rate >= self.threshold

    def to_json(
        self,
        *,
        org_id: uuid.UUID | None,
        include_samples: bool,
        include_benchmark: bool,
    ) -> dict[str, Any]:
        """Return evidence without agent names, org names, or manifest content."""
        status = "no_data" if not self.has_data else "pass" if self.passed else "fail"
        return {
            "ok": self.passed,
            "status": status,
            "org_id": str(org_id) if org_id is not None else None,
            "include_samples": include_samples,
            "include_benchmark": include_benchmark,
            "threshold": self.threshold,
            "min_occurrences": self.min_occurrences,
            "template_count": self.total,
            "reused_count": self.reused,
            "reuse_rate": self.rate,
            "occurrence_counts": sorted(self.occurrences.values()),
        }


def _agent_names_from_manifest(agents_used: dict[str, Any] | None) -> set[str]:
    if not agents_used:
        return set()
    names: set[str] = set()
    for value in agents_used.values():
        if isinstance(value, str) and value:
            names.add(value)
    return names


def is_benchmark_org_name(name: str | None) -> bool:
    if not name:
        return False
    return name in BENCHMARK_ORG_NAMES or any(
        name.startswith(prefix) for prefix in BENCHMARK_ORG_PREFIXES
    )


def compute_reuse_summary(
    templates: list[RoleTemplateKey],
    manifests: list[tuple[uuid.UUID, dict[str, Any] | None]],
    *,
    threshold: float,
    min_occurrences: int,
) -> ReuseSummary:
    template_set = set(templates)
    occurrences = {tpl: 0 for tpl in templates}
    for org_id, agents_used in manifests:
        names = _agent_names_from_manifest(agents_used)
        for name in names:
            key = RoleTemplateKey(org_id=org_id, name=name)
            if key in template_set:
                occurrences[key] += 1
    reused = sum(1 for count in occurrences.values() if count >= min_occurrences)
    return ReuseSummary(
        total=len(templates),
        reused=reused,
        threshold=threshold,
        min_occurrences=min_occurrences,
        occurrences=occurrences,
    )


async def _load_inputs(
    org_id: uuid.UUID | None,
    *,
    include_samples: bool,
    include_benchmark: bool = False,
) -> tuple[list[RoleTemplateKey], list[tuple[uuid.UUID, dict[str, Any] | None]]]:
    init_engine()
    async with get_sessionmaker()() as session:
        tpl_q = (
            select(RoleTemplate, Org.name)
            .outerjoin(Org, RoleTemplate.owner_org_id == Org.id)
            .where(
                RoleTemplate.source == "generated",
                RoleTemplate.status == "active",
            )
        )
        mf_q = (
            select(RunManifest.org_id, RunManifest.agents_used, Org.name)
            .outerjoin(Org, RunManifest.org_id == Org.id)
            .where(RunManifest.agents_used.is_not(None))
        )
        if org_id is not None:
            tpl_q = tpl_q.where(RoleTemplate.owner_org_id == org_id)
            mf_q = mf_q.where(RunManifest.org_id == org_id)
        templates = []
        for t, org_name in (await session.execute(tpl_q)).all():
            if not include_benchmark and is_benchmark_org_name(org_name):
                continue
            meta = t.meta or {}
            if not include_samples and meta.get("sample") is True:
                continue
            templates.append(RoleTemplateKey(org_id=t.owner_org_id, name=t.name))
        manifests = [
            (oid, agents)
            for oid, agents, org_name in (await session.execute(mf_q)).all()
            if include_benchmark or not is_benchmark_org_name(org_name)
        ]
        return templates, manifests


async def run(
    org_id: uuid.UUID | None,
    threshold: float,
    min_occurrences: int,
    *,
    include_samples: bool = False,
    include_benchmark: bool = False,
    json_out: str | None = None,
) -> int:
    templates, manifests = await _load_inputs(
        org_id,
        include_samples=include_samples,
        include_benchmark=include_benchmark,
    )
    summary = compute_reuse_summary(
        templates,
        manifests,
        threshold=threshold,
        min_occurrences=min_occurrences,
    )
    _write_json(
        json_out,
        summary.to_json(
            org_id=org_id,
            include_samples=include_samples,
            include_benchmark=include_benchmark,
        ),
    )

    scope = f"org={org_id}" if org_id else "all orgs"
    print(f"R4 角色模板复用率验证门：{scope}")
    print(f"样本 role_template(generated/active)：{summary.total}")
    print(f"最小机制样本：{'包含' if include_samples else '排除'}（meta.sample=true）")
    print(f"benchmark/smoke org：{'包含' if include_benchmark else '排除'}")
    print(f"复用定义：manifest 出现次数 >= {summary.min_occurrences}")
    if not summary.has_data:
        print("验证门：NO DATA（尚无 generated role_template 样本）")
        return 2

    for key, count in sorted(summary.occurrences.items(), key=lambda item: item[0].name):
        flag = "✅" if count >= summary.min_occurrences else "·"
        print(f"{flag} {key.name}  org={key.org_id}  occurrences={count}")

    print("\n── 汇总 ──")
    print(
        f"R4 复用率 {summary.reused}/{summary.total} = {summary.rate:.0%} "
        f"目标≥{summary.threshold:.0%}"
    )
    print(f"验证门：{'✅ PASS' if summary.passed else '❌ FAIL'}")
    return 0 if summary.passed else 1


def _write_json(path: str | None, payload: dict[str, Any]) -> None:
    if path is None:
        return
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--org-id", type=uuid.UUID, default=None, help="只统计指定 org")
    parser.add_argument("--threshold", type=float, default=0.6, help="通过阈值，默认 0.6")
    parser.add_argument(
        "--min-occurrences",
        type=int,
        default=2,
        help="Agent 名至少出现在多少个 manifest 中才算复用，默认 2",
    )
    parser.add_argument(
        "--include-samples",
        action="store_true",
        help="包含 seed_reuse_sample.py 写入的 meta.sample=true 最小机制样本",
    )
    parser.add_argument(
        "--include-benchmark",
        action="store_true",
        help="包含 M7 验收门 / R4 smoke 等 benchmark org；默认排除以代表真实业务口径",
    )
    parser.add_argument("--json-out", default=None, help="credential-safe JSON evidence path")
    args = parser.parse_args()
    raise SystemExit(
        asyncio.run(
            run(
                args.org_id,
                args.threshold,
                args.min_occurrences,
                include_samples=args.include_samples,
                include_benchmark=args.include_benchmark,
                json_out=args.json_out,
            )
        )
    )


if __name__ == "__main__":
    main()
