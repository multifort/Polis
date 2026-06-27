"""集成测试（TD-032 Skill 生成链 + 风险分级放行）。

安全分级：manual（playbook，无副作用）过自动 eval → 自动 published（无人卡，同轮可用）；
未过 → 撞人审墙（draft + skill_review，人审通过才发布）。副作用来自工具，不来自提示词。
"""

from __future__ import annotations

import asyncio
import uuid

from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from polis.config import get_settings
from polis.modules.model.gateway import ChatResponse, StubModelGateway
from polis.modules.planner.composer import compose_agent
from polis.modules.planner.skillgen import generate_skill_draft, publish_skill


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


# generate_skill_draft 的 3 次 LLM 调用：① 写 playbook ② 自动 eval 试产出 ③ judge 分数
def _gen_script(judge: str) -> list[ChatResponse]:
    return [
        ChatResponse(content="## 操作手册\n步骤1：..."),
        ChatResponse(content="示例产出：..."),
        ChatResponse(content=judge),
    ]


def test_manual_skill_auto_publish_no_human(pg_url: str) -> None:
    """manual 过自动 eval(judge≥τ) → 自动 published/community + 留审计痕(approved)，不卡人。"""
    org_id = _seed_org_model(pg_url, get_settings().default_chat_model)
    cap = f"gen.auto_{uuid.uuid4().hex[:6]}"

    async def _run() -> None:
        engine = create_async_engine(get_settings().database_url)
        try:
            async with async_sessionmaker(engine)() as s:
                gw = StubModelGateway(script=_gen_script("0.9"))
                skill = await generate_skill_draft(s, org_id, cap, gw)
                row = (
                    await s.execute(
                        text("SELECT status, trust FROM skill WHERE id = :i").bindparams(i=skill.id)
                    )
                ).first()
                assert tuple(row) == ("published", "community")
                ap = (
                    await s.execute(
                        text(
                            "SELECT status, (payload->>'auto_eval') FROM approval WHERE ref_id = :r"
                        ).bindparams(r=str(skill.id))
                    )
                ).first()
                assert ap[0] == "approved"  # 审计痕：机器放行
                assert float(ap[1]) == 0.9
                await s.rollback()
        finally:
            await engine.dispose()

    asyncio.run(_run())


def test_manual_skill_low_eval_hits_human_wall_then_publish(pg_url: str) -> None:
    """manual 自动 eval 不过(judge<τ) → 撞人审墙(draft + pending)；人审通过才 published。"""
    org_id = _seed_org_model(pg_url, get_settings().default_chat_model)
    cap = f"gen.wall_{uuid.uuid4().hex[:6]}"

    async def _run() -> None:
        engine = create_async_engine(get_settings().database_url)
        try:
            async with async_sessionmaker(engine)() as s:
                gw = StubModelGateway(script=_gen_script("0.2"))
                skill = await generate_skill_draft(s, org_id, cap, gw)
                row = (
                    await s.execute(
                        text("SELECT status, trust FROM skill WHERE id = :i").bindparams(i=skill.id)
                    )
                ).first()
                assert tuple(row) == ("draft", "private")  # 安全红线：未发布
                ap = await s.scalar(
                    text("SELECT status FROM approval WHERE ref_id = :r").bindparams(
                        r=str(skill.id)
                    )
                )
                assert ap == "pending"  # 待人审

                # 幂等：同 cap 再生成 → 复用草稿，不重复建审批
                await generate_skill_draft(
                    s, org_id, cap, StubModelGateway(script=_gen_script("0.2"))
                )
                n = await s.scalar(
                    text("SELECT count(*) FROM approval WHERE ref_id = :r").bindparams(
                        r=str(skill.id)
                    )
                )
                assert n == 1

                # 人审通过 → published/verified
                assert await publish_skill(s, org_id, skill.id) is True
                pub = (
                    await s.execute(
                        text("SELECT status, trust FROM skill WHERE id = :i").bindparams(i=skill.id)
                    )
                ).first()
                assert tuple(pub) == ("published", "verified")
                await s.rollback()
        finally:
            await engine.dispose()

    asyncio.run(_run())


def test_compose_uses_auto_published_skill_same_run(pg_url: str) -> None:
    """缺 Skill 的 manual 能力自动放行 → compose 同轮就拼出 active Agent（无人卡的智能路径）。"""
    org_id = _seed_org_model(pg_url, get_settings().default_chat_model)
    cap = f"gen.same_{uuid.uuid4().hex[:6]}"

    async def _run() -> None:
        engine = create_async_engine(get_settings().database_url)
        try:
            async with async_sessionmaker(engine)() as s:
                # 5 次调用：generate(playbook,trial,judge=0.9) + trial_endorse(produce,judge=0.9)
                gw = StubModelGateway(
                    script=_gen_script("0.9")
                    + [ChatResponse(content="示例产出"), ChatResponse(content="0.9")]
                )
                agent = await compose_agent(s, org_id, [cap], gateway=gw)
                assert agent is not None and agent.status == "active"
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
                # 低分 → 留 draft，便于测 publish_skill
                skill = await generate_skill_draft(
                    s, org_id, cap, StubModelGateway(script=_gen_script("0.2"))
                )
                assert await publish_skill(s, other, skill.id) is False  # 别的 org 不行
                assert await publish_skill(s, org_id, skill.id) is True  # 本 org 可以
                assert await publish_skill(s, org_id, skill.id) is False  # 非 draft 再发 → False
                await s.rollback()
        finally:
            await engine.dispose()

    asyncio.run(_run())
