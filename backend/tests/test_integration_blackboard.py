"""集成测试（V2-B1）：任务黑板——依赖摘要注入 + read_node_output 懒加载 + org 隔离。"""

from __future__ import annotations

import asyncio
import json
import uuid

from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from polis.config import get_settings
from polis.modules.memory.models import ResultEnvelope
from polis.modules.model.gateway import ToolCall
from polis.modules.runtime import blackboard
from polis.modules.runtime.mcp import McpRegistry, McpRuntime


def _make_org_task(pg_url: str) -> tuple[uuid.UUID, uuid.UUID]:
    """造一个 org + task_run，返回 (org_id, task_id)。"""
    engine = create_engine(pg_url.replace("+asyncpg", "+psycopg2"))
    try:
        with engine.begin() as conn:
            uid = conn.execute(
                text("INSERT INTO app_user (email) VALUES (:e) RETURNING id"),
                {"e": f"bb_{uuid.uuid4().hex[:8]}@polis.dev"},
            ).scalar()
            oid = conn.execute(
                text("INSERT INTO org (name, owner_user_id) VALUES ('黑板公司', :u) RETURNING id"),
                {"u": uid},
            ).scalar()
            tid = conn.execute(
                text("INSERT INTO task_run (org_id, status) VALUES (:o, 'running') RETURNING id"),
                {"o": oid},
            ).scalar()
            return uuid.UUID(str(oid)), uuid.UUID(str(tid))
    finally:
        engine.dispose()


def test_blackboard_dep_inject_lazyload_and_isolation(pg_url: str) -> None:
    org_a, task_a = _make_org_task(pg_url)
    org_b, _task_b = _make_org_task(pg_url)

    async def _run() -> None:
        engine = create_async_engine(get_settings().database_url)
        try:
            async with async_sessionmaker(engine)() as s:
                # 写 A 的两个节点产出（content 全文 + summary 摘要）
                for nid, full in [("n1", "上游一" * 50), ("n2", "上游二的详细分析" * 80)]:
                    s.add(
                        ResultEnvelope(
                            org_id=org_a,
                            task_id=task_a,
                            node_id=nid,
                            status="done",
                            summary=blackboard.summarize(full),
                            content=full,
                            tokens=blackboard.rough_tokens(full),
                        )
                    )
                await s.flush()

                # ① 依赖摘要注入：下游 n3 拿到 n1/n2 的摘要（确定可靠）
                brief = await blackboard.dep_briefs(s, org_a, task_a, ["n1", "n2"])
                assert "n1" in brief and "n2" in brief
                assert "read_node_output" in brief  # 提示可懒加载全文

                # ② read_node_output：按 id 拿全文
                r1 = await blackboard.read_node_output(s, org_a, task_a, "n1")
                assert r1["found"] is True
                assert r1["content"].startswith("上游一")

                # 不存在的节点
                rx = await blackboard.read_node_output(s, org_a, task_a, "n9")
                assert rx["found"] is False

                # ③ org 隔离：B 看不到 A 的产出
                brief_b = await blackboard.dep_briefs(s, org_b, task_a, ["n1", "n2"])
                assert brief_b == ""
                rb = await blackboard.read_node_output(s, org_b, task_a, "n1")
                assert rb["found"] is False

                # ④ 工具经 McpRuntime(ahandler) 可调通
                reg = McpRegistry()
                blackboard.register_blackboard_tools(reg)
                rt = McpRuntime(reg, ctx=blackboard.ToolCtx(s, org_a, task_a))
                tc = ToolCall(id="t1", name="read_node_output", arguments={"node_id": "n2"})
                parsed = json.loads(await rt.call(tc))
                assert parsed["found"] is True and parsed["node_id"] == "n2"
        finally:
            await engine.dispose()

    asyncio.run(_run())


def test_summarize_truncates_and_tokens_positive() -> None:
    long = "字" * 1000
    assert blackboard.summarize(long).endswith("…")
    assert len(blackboard.summarize(long)) <= blackboard.SUMMARY_CHARS + 1
    assert blackboard.rough_tokens(long) >= 1
    assert blackboard.summarize(None) == ""
