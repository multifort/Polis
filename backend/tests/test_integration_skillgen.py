"""集成测试（TD-032 Skill 生成链）：缺 Skill → 草稿 + 人审墙 → 发布 → 可拼装。

安全红线：生成的 Skill 必须 draft/private、绝不自动发布；只有 publish_skill（人审通过）后
其能力才进入检索、编配器才能拼装。
"""

from __future__ import annotations

import asyncio
import uuid

from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from polis.config import get_settings
from polis.modules.model.gateway import ChatResponse, StubModelGateway
from polis.modules.planner.composer import compose_agent
from polis.modules.planner.skillgen import publish_skill


def _seed_org_model(pg_url: str, model_id: str) -> uuid.UUID:
    engine = create_engine(pg_url.replace("+asyncpg", "+psycopg2"))
    try:
        with engine.begin() as conn:
            uid = conn.execute(
                text("INSERT INTO app_user (email) VALUES (:e) RETURNING id"),
                {"e": f"sg_{uuid.uuid4().hex[:8]}@polis.dev"},
            ).scalar()
            oid = conn.execute(
                text("INSERT INTO org (name, owner_user_id) VALUES ('技能链', :u) RETURNING id"),
                {"u": uid},
            ).scalar()
            conn.execute(
                text("INSERT INTO model_catalog (id) VALUES (:m) ON CONFLICT (id) DO NOTHING"),
                {"m": model_id},
            )
            return uuid.UUID(str(oid))
    finally:
        engine.dispose()


def test_skill_generation_wall_then_publish_then_compose(pg_url: str) -> None:
    org_id = _seed_org_model(pg_url, get_settings().default_chat_model)
    cap = f"gen.cap_{uuid.uuid4().hex[:6]}"

    async def _run() -> None:
        engine = create_async_engine(get_settings().database_url)
        try:
            async with async_sessionmaker(engine)() as s:
                # ① 缺 Skill 的能力拼装 → 生成草稿 + 人审墙；本节点不覆盖（返回 None）
                gw1 = StubModelGateway(script=[ChatResponse(content="## 操作手册\n步骤1：...")])
                agent = await compose_agent(s, org_id, [cap], gateway=gw1)
                assert agent is None

                skill = (
                    await s.execute(
                        text(
                            "SELECT id, status, trust, visibility FROM skill "
                            "WHERE capability = :c AND owner_org_id = :o"
                        ).bindparams(c=cap, o=org_id)
                    )
                ).first()
                assert skill is not None
                sid, sstatus, strust, svis = skill
                # 安全红线：草稿、私有、未发布
                assert sstatus == "draft" and strust == "private" and svis == "org"

                # 草稿内容落库 + 待人审 approval
                content = await s.scalar(
                    text("SELECT content FROM skill_version WHERE skill_id = :s").bindparams(s=sid)
                )
                assert content and "操作手册" in content
                ap = (
                    await s.execute(
                        text(
                            "SELECT status, kind FROM approval WHERE ref_id = :r AND org_id = :o"
                        ).bindparams(r=str(sid), o=org_id)
                    )
                ).first()
                assert tuple(ap) == ("pending", "skill_review")

                # ② 幂等：同 cap 再拼 → 复用草稿，不重复建审批
                gw_dup = StubModelGateway(script=[ChatResponse(content="重复不应发生")])
                assert await compose_agent(s, org_id, [cap], gateway=gw_dup) is None
                n_ap = await s.scalar(
                    text(
                        "SELECT count(*) FROM approval WHERE ref_id = :r AND org_id = :o"
                    ).bindparams(r=str(sid), o=org_id)
                )
                assert n_ap == 1

                # ③ 人审通过 → 发布草稿
                assert await publish_skill(s, org_id, sid) is True
                pub = (
                    await s.execute(
                        text("SELECT status, trust FROM skill WHERE id = :s").bindparams(s=sid)
                    )
                ).first()
                assert tuple(pub) == ("published", "verified")

                # ④ 发布后能力可用 → 同 cap 拼装成功（试产出背书过 → active）
                # _trial_endorse 两次调用：① 试产出 ② judge 分数
                gw2 = StubModelGateway(
                    script=[ChatResponse(content="示例产出"), ChatResponse(content="0.9")]
                )
                agent2 = await compose_agent(s, org_id, [cap], gateway=gw2)
                assert agent2 is not None and agent2.status == "active"
                await s.rollback()
        finally:
            await engine.dispose()

    asyncio.run(_run())


def test_publish_skill_only_own_draft(pg_url: str) -> None:
    """publish_skill 只发布本 org 的 draft：非本 org / 非 draft → False。"""
    org_id = _seed_org_model(pg_url, get_settings().default_chat_model)
    other = _seed_org_model(pg_url, get_settings().default_chat_model)
    cap = f"gen.own_{uuid.uuid4().hex[:6]}"

    async def _run() -> None:
        engine = create_async_engine(get_settings().database_url)
        try:
            async with async_sessionmaker(engine)() as s:
                gw = StubModelGateway(script=[ChatResponse(content="手册")])
                await compose_agent(s, org_id, [cap], gateway=gw)
                sid = await s.scalar(
                    text("SELECT id FROM skill WHERE capability = :c").bindparams(c=cap)
                )
                assert sid is not None
                # 别的 org 不能发布
                assert await publish_skill(s, other, sid) is False
                # 本 org 可以
                assert await publish_skill(s, org_id, sid) is True
                # 已发布再发布 → False（非 draft）
                assert await publish_skill(s, org_id, sid) is False
                await s.rollback()
        finally:
            await engine.dispose()

    asyncio.run(_run())
