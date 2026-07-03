"""为 R4 role_template 复用率 gate 写入最小 live 验证样本。

默认 dry-run，只打印将要写入的内容；显式 `--write` 才改库。

用法：
  uv run python scripts/r4/seed_reuse_sample.py
  uv run python scripts/r4/seed_reuse_sample.py --write
  uv run python scripts/r4/seed_reuse_sample.py --write --org-id <org_uuid>
  uv run python scripts/r4/role_template_reuse_gate.py --threshold 0.6
"""

from __future__ import annotations

import argparse
import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from polis.db.session import get_sessionmaker, init_engine
from polis.modules.observability import repository as obs_repo
from polis.modules.observability.models import RunManifest
from polis.modules.org.models import AppUser, Org, OrgMember, RoleTemplate
from polis.modules.planner import repository as plan_repo

DEFAULT_AGENT_NAME = "弹性组队·r4.reuse.sample"
DEFAULT_ORG_NAME = "R4复用率样本公司"
DEFAULT_USER_EMAIL = "r4-reuse-sample@polis.local"


async def _ensure_sample_org(session: Any) -> uuid.UUID:
    user = await session.scalar(select(AppUser).where(AppUser.email == DEFAULT_USER_EMAIL))
    if user is None:
        user = AppUser(
            email=DEFAULT_USER_EMAIL,
            password_hash=None,
            display_name="R4 reuse sample",
        )
        session.add(user)
        await session.flush()

    org = await session.scalar(
        select(Org).where(Org.owner_user_id == user.id, Org.name == DEFAULT_ORG_NAME)
    )
    if org is None:
        org = Org(name=DEFAULT_ORG_NAME, owner_user_id=user.id, charter="R4 gate sample")
        session.add(org)
        await session.flush()
        session.add(OrgMember(org_id=org.id, user_id=user.id, role="owner"))
        await session.flush()
    return org.id


async def _ensure_role_template(session: Any, org_id: uuid.UUID, agent_name: str) -> RoleTemplate:
    tpl = await session.scalar(
        select(RoleTemplate).where(
            RoleTemplate.owner_org_id == org_id,
            RoleTemplate.name == agent_name,
            RoleTemplate.source == "generated",
        )
    )
    if tpl is not None:
        return tpl

    tpl = RoleTemplate(
        name=agent_name,
        version="1.0",
        persona="R4 gate sample generated role template.",
        skill_refs=[{"name": "r4.reuse.sample", "kind": "manual"}],
        capabilities=["r4.reuse.sample"],
        visibility="private",
        owner_org_id=org_id,
        status="active",
        source="generated",
        embedding=None,
        meta={
            "sample": True,
            "purpose": "r4_reuse_gate",
            "created_by": "scripts/r4/seed_reuse_sample.py",
        },
    )
    session.add(tpl)
    await session.flush()
    return tpl


async def _manifest_occurrences(session: Any, org_id: uuid.UUID, agent_name: str) -> int:
    rows = (
        await session.execute(
            select(RunManifest.agents_used).where(
                RunManifest.org_id == org_id,
                RunManifest.agents_used.is_not(None),
            )
        )
    ).all()
    count = 0
    for (agents_used,) in rows:
        if isinstance(agents_used, dict) and agent_name in set(agents_used.values()):
            count += 1
    return count


async def _create_manifest_sample(
    session: Any, org_id: uuid.UUID, agent_name: str, idx: int
) -> None:
    dag = {
        "workflow_name": "r4_reuse_sample",
        "goal": f"R4 reuse sample #{idx}",
        "nodes": [
            {
                "id": "n1",
                "type": "agent",
                "deps": [],
                "required_capabilities": ["r4.reuse.sample"],
                "executor": "lite-agent",
            }
        ],
    }
    plan = await plan_repo.create_plan(
        session,
        org_id=org_id,
        goal=dag["goal"],
        dag=dag,
        version="generated",
        estimated_cost_cents=1,
    )
    run = await plan_repo.create_task_run(
        session,
        org_id,
        plan.id,
        f"r4-reuse-sample-{idx}-{uuid.uuid4().hex[:8]}",
        status="done",
    )
    run.finished_at = datetime.now(UTC)
    await obs_repo.create_run_manifest(
        session,
        task_id=run.id,
        org_id=org_id,
        plan_snapshot=dag,
        plan_version="generated",
        models_used={"chat": "sample"},
        agents_used={"n1": agent_name},
    )


async def run(
    *,
    write: bool,
    org_id: uuid.UUID | None,
    agent_name: str,
    occurrences: int,
) -> int:
    init_engine()
    async with get_sessionmaker()() as session:
        target_org_id = org_id or await _ensure_sample_org(session)
        existing = await _manifest_occurrences(session, target_org_id, agent_name)
        needed = max(0, occurrences - existing)

        print("R4 reuse gate sample")
        print(f"org_id={target_org_id}")
        print(f"agent_name={agent_name}")
        print(f"existing_occurrences={existing}")
        print(f"target_occurrences={occurrences}")
        print(f"needed_writes={needed}")

        if not write:
            print("dry-run：未写入。加 --write 才会创建 role_template / manifest 样本。")
            await session.rollback()
            return 0

        await _ensure_role_template(session, target_org_id, agent_name)
        for idx in range(existing + 1, existing + needed + 1):
            await _create_manifest_sample(session, target_org_id, agent_name, idx)
        await session.commit()
        print("write：完成。现在可运行 role_template_reuse_gate.py 验证。")
        return 0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true", help="真正写入样本；默认只 dry-run")
    parser.add_argument(
        "--org-id",
        type=uuid.UUID,
        default=None,
        help="写入指定 org；默认创建/复用样本 org",
    )
    parser.add_argument(
        "--agent-name",
        default=DEFAULT_AGENT_NAME,
        help="样本 generated Agent/role_template 名",
    )
    parser.add_argument("--occurrences", type=int, default=2, help="manifest 出现次数目标，默认 2")
    args = parser.parse_args()
    raise SystemExit(
        asyncio.run(
            run(
                write=args.write,
                org_id=args.org_id,
                agent_name=args.agent_name,
                occurrences=args.occurrences,
            )
        )
    )


if __name__ == "__main__":
    main()
