"""为 R4 gate 写入“自然编配路径”的 dev/live smoke 数据。

区别于 `seed_reuse_sample.py`：
- 本脚本不会直接插入 role_template；
- 会创建/复用一个专用 org + published manual Skill；
- 通过 `compose_agent` 自然拼装 generated Agent，并由 composer 沉淀 role_template；
- 再补足 Run Manifest 中该 Agent 的出现次数，让默认 gate 可量化。

默认 dry-run，只打印将要执行的内容；显式 `--write` 才改库。

用法：
  uv run python scripts/r4/seed_natural_reuse_smoke.py
  uv run python scripts/r4/seed_natural_reuse_smoke.py --write
  uv run python scripts/r4/role_template_reuse_gate.py --threshold 0.6 --include-benchmark
"""

from __future__ import annotations

import argparse
import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import select

from polis.db.session import get_sessionmaker, init_engine
from polis.modules.observability import repository as obs_repo
from polis.modules.observability.models import RunManifest
from polis.modules.org.models import AppUser, Org, OrgMember
from polis.modules.planner import repository as plan_repo
from polis.modules.planner.composer import compose_agent
from polis.modules.runtime.models import Skill, SkillVersion

DEFAULT_CAPABILITY = "r4.reuse.natural"
DEFAULT_ORG_NAME = "R4自然复用Smoke公司"
DEFAULT_USER_EMAIL = "r4-natural-smoke@polis.local"
DEFAULT_SKILL_NAME = "r4-natural-reuse-playbook"


def _agent_name(capability: str) -> str:
    return f"弹性组队·{capability}"


async def _ensure_org(session: Any) -> uuid.UUID:
    user = await session.scalar(select(AppUser).where(AppUser.email == DEFAULT_USER_EMAIL))
    if user is None:
        user = AppUser(
            email=DEFAULT_USER_EMAIL,
            password_hash=None,
            display_name="R4 natural smoke",
        )
        session.add(user)
        await session.flush()

    org = await session.scalar(
        select(Org).where(Org.owner_user_id == user.id, Org.name == DEFAULT_ORG_NAME)
    )
    if org is None:
        org = Org(name=DEFAULT_ORG_NAME, owner_user_id=user.id, charter="R4 natural smoke")
        session.add(org)
        await session.flush()
        session.add(OrgMember(org_id=org.id, user_id=user.id, role="owner"))
        await session.flush()
    return cast(uuid.UUID, org.id)


async def _ensure_skill(
    session: Any,
    org_id: uuid.UUID,
    *,
    capability: str,
    skill_name: str,
) -> Skill:
    skill = await session.scalar(select(Skill).where(Skill.name == skill_name))
    if skill is None:
        skill = Skill(
            name=skill_name,
            kind="manual",
            trust="verified",
            status="published",
            capability=capability,
            owner_org_id=org_id,
            visibility="org",
        )
        session.add(skill)
        await session.flush()
        session.add(
            SkillVersion(
                skill_id=skill.id,
                version="v1",
                content=f"{skill_name} playbook for {capability}",
            )
        )
        await session.flush()
    return cast(Skill, skill)


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


async def _create_manifest(
    session: Any,
    org_id: uuid.UUID,
    *,
    capability: str,
    agent_name: str,
    idx: int,
) -> None:
    dag: dict[str, Any] = {
        "workflow_name": "r4_natural_reuse_smoke",
        "goal": f"R4 natural reuse smoke #{idx}",
        "nodes": [
            {
                "id": "n1",
                "type": "agent",
                "deps": [],
                "required_capabilities": [capability],
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
        f"r4-natural-smoke-{idx}-{uuid.uuid4().hex[:8]}",
        status="done",
    )
    run.finished_at = datetime.now(UTC)
    await obs_repo.create_run_manifest(
        session,
        task_id=run.id,
        org_id=org_id,
        plan_snapshot=dag,
        plan_version="generated",
        models_used={"chat": "smoke"},
        agents_used={"n1": agent_name},
    )


async def run(
    *,
    write: bool,
    capability: str,
    skill_name: str,
    occurrences: int,
) -> int:
    init_engine()
    async with get_sessionmaker()() as session:
        org_id = await _ensure_org(session)
        agent_name = _agent_name(capability)
        existing = await _manifest_occurrences(session, org_id, agent_name)
        needed = max(0, occurrences - existing)

        print("R4 natural reuse smoke")
        print(f"org_id={org_id}")
        print(f"capability={capability}")
        print(f"skill_name={skill_name}")
        print(f"agent_name={agent_name}")
        print(f"existing_occurrences={existing}")
        print(f"target_occurrences={occurrences}")
        print(f"needed_writes={needed}")

        if not write:
            print("dry-run：未写入。加 --write 才会 compose Agent 并创建 manifest。")
            await session.rollback()
            return 0

        await _ensure_skill(session, org_id, capability=capability, skill_name=skill_name)
        agent = await compose_agent(session, org_id, [capability], gateway=None)
        if agent is None:
            await session.rollback()
            print("write：compose_agent 未生成 active Agent，已回滚。")
            return 1

        for idx in range(existing + 1, existing + needed + 1):
            await _create_manifest(
                session,
                org_id,
                capability=capability,
                agent_name=agent.name,
                idx=idx,
            )
        await session.commit()
        print("write：完成。现在可运行 role_template_reuse_gate.py --include-benchmark 验证。")
        return 0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true", help="真正写入 smoke 数据；默认 dry-run")
    parser.add_argument("--capability", default=DEFAULT_CAPABILITY, help="用于自然拼装的能力")
    parser.add_argument("--skill-name", default=DEFAULT_SKILL_NAME, help="用于自然拼装的 Skill 名")
    parser.add_argument("--occurrences", type=int, default=2, help="manifest 出现次数目标，默认 2")
    args = parser.parse_args()
    raise SystemExit(
        asyncio.run(
            run(
                write=args.write,
                capability=args.capability,
                skill_name=args.skill_name,
                occurrences=args.occurrences,
            )
        )
    )


if __name__ == "__main__":
    main()
