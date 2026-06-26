"""集成测试（A3 编配生成）：节点无现成 Agent → 拼已审 Skill 成 Agent（§5.2–5.3）。

直连临时库（请求外，显式 org 过滤，不依赖 RLS，TD-015）。播一个 published Skill 提供新能力，
验证：① select_agent 未命中 → compose_agent 用 Skill 拼出 active 的 generated Agent；
② 幂等复用（同能力集不重复造）；③ 缺 Skill → None；④ route_or_compose 把节点路由到组队 Agent。
"""

from __future__ import annotations

import asyncio
import uuid

from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from polis.config import get_settings
from polis.modules.planner.composer import compose_agent, route_or_compose
from polis.modules.planner.schemas import PlanDag, PlanNode


def _seed(pg_url: str, cap: str, skill_name: str) -> uuid.UUID:
    """造 org + 一个 published Skill（capability=cap, public 可见）。返回 org_id。"""
    engine = create_engine(pg_url.replace("+asyncpg", "+psycopg2"))
    try:
        with engine.begin() as conn:
            uid = conn.execute(
                text("INSERT INTO app_user (email) VALUES (:e) RETURNING id"),
                {"e": f"cmp_{uuid.uuid4().hex[:8]}@polis.dev"},
            ).scalar()
            oid = conn.execute(
                text("INSERT INTO org (name, owner_user_id) VALUES ('编配公司', :u) RETURNING id"),
                {"u": uid},
            ).scalar()
            # org 私有可见（非 public）：避免「公共能力」泄漏到其它测试的空 org
            conn.execute(
                text(
                    "INSERT INTO skill (name, kind, status, trust, capability, visibility, "
                    "owner_org_id) VALUES (:n, 'manual', 'published', 'verified', :c, 'org', :o)"
                ),
                {"n": skill_name, "c": cap, "o": oid},
            )
            return uuid.UUID(str(oid))
    finally:
        engine.dispose()


def test_compose_from_skill_idempotent_and_missing(pg_url: str) -> None:
    sfx = uuid.uuid4().hex[:6]
    cap = f"compose.cap_{sfx}"
    missing_cap = f"compose.missing_{sfx}"
    skill_name = f"skill_{sfx}"
    org_id = _seed(pg_url, cap, skill_name)

    async def _run() -> None:
        engine = create_async_engine(get_settings().database_url)
        try:
            async with async_sessionmaker(engine)() as s:
                # ① 无现成 Agent，但有 Skill → 拼装出 active 的 generated Agent
                agent = await compose_agent(s, org_id, [cap])
                assert agent is not None
                assert agent.source == "generated" and agent.status == "active"
                first_id = agent.id

                # 版本配置记录出处 + 能力派生 + 技能引用
                ver = await s.scalar(
                    text("SELECT config FROM agent_version WHERE agent_id = :a").bindparams(
                        a=agent.id
                    )
                )
                assert ver["capabilities"] == [cap]
                assert ver["skills"] == [skill_name]
                assert ver["provenance"]["composed_from"][cap] == skill_name

                # agent_capability 回填
                cap_row = await s.scalar(
                    text("SELECT capability FROM agent_capability WHERE agent_id = :a").bindparams(
                        a=agent.id
                    )
                )
                assert cap_row == cap

                # ② 幂等：同能力集再拼 → 复用同一 Agent，不新建
                again = await compose_agent(s, org_id, [cap])
                assert again is not None and again.id == first_id

                # ③ 缺 Skill 的能力 → 放弃拼装（A3 不生成草稿）
                none_agent = await compose_agent(s, org_id, [cap, missing_cap])
                assert none_agent is None

                # ④ route_or_compose：节点能力无现成 Agent → 路由到拼装 Agent
                dag = PlanDag(
                    workflow_name="wf",
                    goal="g",
                    nodes=[
                        PlanNode(id="n1", type="agent", required_capabilities=[cap]),
                        PlanNode(id="n2", type="agent", required_capabilities=[missing_cap]),
                    ],
                )
                routing = await route_or_compose(s, org_id, dag)
                assert routing["n1"] == agent.name  # 命中拼装 Agent
                assert routing["n2"] is None  # 缺 Skill → 未覆盖
                await s.rollback()
        finally:
            await engine.dispose()

    asyncio.run(_run())
