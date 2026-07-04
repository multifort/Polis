"""R4 角色模板自动沉淀复用率验证门。

统计 live DB 中 generated role_template 对应的 Agent 是否在后续运行 manifest 中被复用。
口径：
  - 分母：status=active 且 source=generated 的 role_template
  - 分子：该模板同名 Agent 在 run_manifest.agents_used 中出现次数 >= --min-occurrences

默认 --min-occurrences=2：第一次出现通常是沉淀来源/首次使用，第二次及以后才算“后续复用”。

用法：
  uv run python scripts/r4/role_template_reuse_gate.py
  uv run python scripts/r4/role_template_reuse_gate.py --include-samples
  uv run python scripts/r4/role_template_reuse_gate.py --org-id <org_uuid> --threshold 0.6
"""

from __future__ import annotations

import argparse
import asyncio
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select

from polis.db.session import get_sessionmaker, init_engine
from polis.modules.observability.models import RunManifest
from polis.modules.org.models import RoleTemplate


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


def _agent_names_from_manifest(agents_used: dict[str, Any] | None) -> set[str]:
    if not agents_used:
        return set()
    names: set[str] = set()
    for value in agents_used.values():
        if isinstance(value, str) and value:
            names.add(value)
    return names


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
) -> tuple[list[RoleTemplateKey], list[tuple[uuid.UUID, dict[str, Any] | None]]]:
    init_engine()
    async with get_sessionmaker()() as session:
        tpl_q = select(RoleTemplate).where(
            RoleTemplate.source == "generated",
            RoleTemplate.status == "active",
        )
        mf_q = select(RunManifest.org_id, RunManifest.agents_used).where(
            RunManifest.agents_used.is_not(None)
        )
        if org_id is not None:
            tpl_q = tpl_q.where(RoleTemplate.owner_org_id == org_id)
            mf_q = mf_q.where(RunManifest.org_id == org_id)
        templates = []
        for t in (await session.scalars(tpl_q)).all():
            meta = t.meta or {}
            if not include_samples and meta.get("sample") is True:
                continue
            templates.append(RoleTemplateKey(org_id=t.owner_org_id, name=t.name))
        manifests = [(oid, agents) for oid, agents in (await session.execute(mf_q)).all()]
        return templates, manifests


async def run(
    org_id: uuid.UUID | None,
    threshold: float,
    min_occurrences: int,
    *,
    include_samples: bool = False,
) -> int:
    templates, manifests = await _load_inputs(org_id, include_samples=include_samples)
    summary = compute_reuse_summary(
        templates,
        manifests,
        threshold=threshold,
        min_occurrences=min_occurrences,
    )

    scope = f"org={org_id}" if org_id else "all orgs"
    print(f"R4 角色模板复用率验证门：{scope}")
    print(f"样本 role_template(generated/active)：{summary.total}")
    print(f"最小机制样本：{'包含' if include_samples else '排除'}（meta.sample=true）")
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
    args = parser.parse_args()
    raise SystemExit(
        asyncio.run(
            run(
                args.org_id,
                args.threshold,
                args.min_occurrences,
                include_samples=args.include_samples,
            )
        )
    )


if __name__ == "__main__":
    main()
