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
from polis.modules.planner.service import plan
from polis.modules.planner.skillgen import (
    ToolSkillSandboxError,
    create_tool_skill_draft,
    generate_skill_draft,
    publish_skill,
)


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


class _EmbeddingGateway(StubModelGateway):
    async def embed(self, texts: list[str]) -> list[list[float] | None]:
        return [[0.01] * 1024 for _ in texts]


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


def test_tool_skill_sandbox_hits_human_wall_then_publish(pg_url: str) -> None:
    """tool skill 必须沙箱过闸，但仍不自动发布；审批通过后才 published/verified。"""
    org_id = _seed_org_model(pg_url, get_settings().default_chat_model)
    cap = f"tool.echo_{uuid.uuid4().hex[:6]}"
    name = f"tool_echo_{uuid.uuid4().hex[:6]}"

    async def _run() -> None:
        engine = create_async_engine(get_settings().database_url)
        try:
            async with async_sessionmaker(engine)() as s:
                skill = await create_tool_skill_draft(
                    s,
                    org_id,
                    cap,
                    name=name,
                    mcp_server="local",
                    tool="echo",
                    description="通过 echo 工具回显输入，用于验证工具型 Skill 沙箱。",
                    io_schema={
                        "type": "object",
                        "properties": {"text": {"type": "string"}},
                        "required": ["text"],
                    },
                    permissions={"effects": "none"},
                    sandbox_args={"text": "sandbox-ok"},
                )
                row = (
                    await s.execute(
                        text("SELECT kind, status, trust FROM skill WHERE id = :i").bindparams(
                            i=skill.id
                        )
                    )
                ).first()
                assert tuple(row) == ("tool", "draft", "private")
                sv = (
                    await s.execute(
                        text(
                            "SELECT tool, permissions FROM skill_version WHERE skill_id = :i"
                        ).bindparams(i=skill.id)
                    )
                ).first()
                assert sv[0] == "echo"
                assert sv[1]["sandbox"]["passed"] is True
                assert sv[1]["sandbox"]["result_preview"] == "sandbox-ok"
                ap = await s.scalar(
                    text("SELECT status FROM approval WHERE ref_id = :r").bindparams(
                        r=str(skill.id)
                    )
                )
                assert ap == "pending"

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


def test_tool_skill_permission_overreach_is_blocked(pg_url: str) -> None:
    """tool skill 声明网络/凭证/写副作用等越界权限时，草稿不会落库。"""
    org_id = _seed_org_model(pg_url, get_settings().default_chat_model)
    cap = f"tool.bad_{uuid.uuid4().hex[:6]}"
    name = f"tool_bad_{uuid.uuid4().hex[:6]}"

    async def _run() -> None:
        engine = create_async_engine(get_settings().database_url)
        try:
            async with async_sessionmaker(engine)() as s:
                try:
                    await create_tool_skill_draft(
                        s,
                        org_id,
                        cap,
                        name=name,
                        mcp_server="local",
                        tool="echo",
                        description="危险工具",
                        io_schema={"type": "object"},
                        permissions={"effects": "write", "network": True},
                        sandbox_args={"text": "blocked"},
                    )
                except ToolSkillSandboxError:
                    pass
                else:  # pragma: no cover - 走到这里就是安全闸失效
                    raise AssertionError("tool skill permission overreach should be blocked")
                count = await s.scalar(
                    text(
                        "SELECT count(*) FROM skill WHERE owner_org_id = :o AND name = :n"
                    ).bindparams(o=org_id, n=name)
                )
                assert count == 0
                await s.rollback()
        finally:
            await engine.dispose()

    asyncio.run(_run())


def test_tool_skill_without_sandbox_cannot_publish(pg_url: str) -> None:
    """防御性校验：即使有人绕过 create_tool_skill_draft，未过 sandbox 的 tool 也不能发布。"""
    org_id = _seed_org_model(pg_url, get_settings().default_chat_model)
    cap = f"tool.unsandboxed_{uuid.uuid4().hex[:6]}"
    name = f"tool_unsandboxed_{uuid.uuid4().hex[:6]}"

    async def _run() -> None:
        engine = create_async_engine(get_settings().database_url)
        try:
            async with async_sessionmaker(engine)() as s:
                skill_id = await s.scalar(
                    text(
                        "INSERT INTO skill (name, kind, status, trust, capability, visibility, "
                        "owner_org_id) VALUES (:n, 'tool', 'draft', 'private', :c, 'org', :o) "
                        "RETURNING id"
                    ).bindparams(n=name, c=cap, o=org_id)
                )
                await s.execute(
                    text(
                        "INSERT INTO skill_version (skill_id, version, content, mcp_server, tool, "
                        "permissions) VALUES (:i, 'v1', 'unsafe', 'local', 'echo', '{}'::jsonb)"
                    ).bindparams(i=skill_id)
                )

                assert await publish_skill(s, org_id, skill_id) is False
                status = await s.scalar(
                    text("SELECT status FROM skill WHERE id = :i").bindparams(i=skill_id)
                )
                assert status == "draft"
                await s.rollback()
        finally:
            await engine.dispose()

    asyncio.run(_run())


def test_goal_proposes_missing_capability_and_plans_same_run(pg_url: str) -> None:
    """TD-032 goal 端可达：无可用能力时，提案新能力→自动发布 Skill→同轮生成 DAG/Agent。"""
    org_id = _seed_org_model(pg_url, get_settings().default_chat_model)
    cap = f"goal.new_{uuid.uuid4().hex[:6]}"

    async def _run() -> None:
        engine = create_async_engine(get_settings().database_url)
        try:
            async with async_sessionmaker(engine)() as s:
                await s.execute(text("DELETE FROM plan_template"))
                gw = _EmbeddingGateway(
                    script=[
                        ChatResponse(
                            content=f'[{{"key":"{cap}","description":"目标需要的新能力"}}]'
                        ),
                        *_gen_script("0.9"),
                        ChatResponse(
                            content=(
                                '{"workflow_name":"wf","goal":"g","budget_cents":1000,'
                                '"nodes":[{"id":"n1","type":"agent","deps":[],'
                                f'"required_capabilities":["{cap}"]'
                                "}]} "
                            )
                        ),
                        ChatResponse(content="拼装 Agent 示例产出"),
                        ChatResponse(content="0.9"),
                    ]
                )
                result = await plan(s, org_id, "一个需要全新能力的目标", gateway=gw)

                assert result.template == "generated"
                assert result.dag.nodes[0].required_capabilities == [cap]
                assert result.routing["n1"] is not None
                skill_status = await s.scalar(
                    text(
                        "SELECT status FROM skill WHERE owner_org_id = :o AND capability = :c"
                    ).bindparams(o=org_id, c=cap)
                )
                assert skill_status == "published"
                await s.rollback()
        finally:
            await engine.dispose()

    asyncio.run(_run())
