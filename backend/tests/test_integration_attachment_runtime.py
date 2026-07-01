"""集成测试（V2-P2b-2）：任务附件的运行时注入——黑板清单默认注入 + read_attachment 懒加载。

覆盖：
① task_run.id → 所属可复用 task.id 的反查（resolve_owner_task_id）；
② 附件清单默认注入（attachments_brief），含文件名/字段/类型 + 懒加载提示；
③ read_attachment：文本类返回正文、二进制类返回元信息提示、不存在返回 found=False；
④ 端到端：agent_runtime.execute() 用确定性 StubModelGateway 跑一个节点，验证附件清单
   真正进入了 Agent 的 prompt（回显在产出 envelope.content 里）——即附件影响了产出。
"""

from __future__ import annotations

import asyncio
import json
import uuid

from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from polis.config import get_settings
from polis.modules.model.gateway import StubModelGateway
from polis.modules.planner import repository as planner_repo
from polis.modules.runtime import agent_runtime, blackboard
from polis.modules.runtime.mcp import McpRegistry, McpRuntime
from polis.seed import seed


class FakeStore:
    """内存对象存储替身：仅供 read_attachment 单测使用。"""

    def __init__(self, data: dict[str, bytes]) -> None:
        self._data = data

    def uri(self, key: str) -> str:
        return f"s3://polis/{key}"

    async def ensure_bucket(self) -> None:
        return None

    async def put(
        self, org_id: str, task_id: str, name: str, data: bytes, content_type: str = ""
    ) -> str:
        self._data[f"{org_id}/{task_id}/{name}"] = data
        return self.uri(f"{org_id}/{task_id}/{name}")

    async def get(self, org_id: str, task_id: str, name: str) -> bytes:
        from polis.modules.storage.client import StorageError

        key = f"{org_id}/{task_id}/{name}"
        if key not in self._data:
            raise StorageError(f"not found: {key}")
        return self._data[key]

    async def delete(self, org_id: str, task_id: str, name: str) -> None:
        self._data.pop(f"{org_id}/{task_id}/{name}", None)

    async def presigned_get_url(
        self, org_id: str, task_id: str, name: str, expires_seconds: int = 900
    ) -> str:
        return f"http://minio.local/{org_id}/{task_id}/{name}"


def _make_org_user(pg_url: str) -> tuple[uuid.UUID, uuid.UUID]:
    """造一个 org + user，返回 (org_id, user_id)。"""
    engine = create_engine(pg_url.replace("+asyncpg", "+psycopg2"))
    try:
        with engine.begin() as conn:
            uid = conn.execute(
                text("INSERT INTO app_user (email) VALUES (:e) RETURNING id"),
                {"e": f"pa_{uuid.uuid4().hex[:8]}@polis.dev"},
            ).scalar()
            oid = conn.execute(
                text("INSERT INTO org (name, owner_user_id) VALUES ('附件公司', :u) RETURNING id"),
                {"u": uid},
            ).scalar()
            return uuid.UUID(str(oid)), uuid.UUID(str(uid))
    finally:
        engine.dispose()


def test_attachment_brief_lazyload_and_isolation(pg_url: str) -> None:
    org_a, user_a = _make_org_user(pg_url)
    org_b, _user_b = _make_org_user(pg_url)

    async def _run() -> None:
        engine = create_async_engine(get_settings().database_url)
        try:
            async with async_sessionmaker(engine)() as s:
                task_a = await planner_repo.create_task(
                    s, org_a, name="供应商分析", goal="分析报价", created_by=user_a
                )
                await planner_repo.create_attachment(
                    s,
                    org_a,
                    task_id=task_a.id,
                    filename="quote.csv",
                    uri=f"s3://polis/{org_a}/{task_a.id}/quote.csv",
                    mime="text/csv",
                    size=100,
                    field="报价单",
                )
                await planner_repo.create_attachment(
                    s,
                    org_a,
                    task_id=task_a.id,
                    filename="scan.pdf",
                    uri=f"s3://polis/{org_a}/{task_a.id}/scan.pdf",
                    mime="application/pdf",
                    size=200,
                )
                await s.flush()

                # ① 附件清单默认注入：含文件名/字段/类型 + 懒加载提示
                brief = await blackboard.attachments_brief(s, org_a, task_a.id)
                assert "quote.csv" in brief and "报价单" in brief and "scan.pdf" in brief
                assert "read_attachment" in brief

                # ② org 隔离：B 看不到 A 的附件
                brief_b = await blackboard.attachments_brief(s, org_b, task_a.id)
                assert brief_b == ""

                # ③ read_attachment：文本类懒加载正文
                store = FakeStore({f"{org_a}/{task_a.id}/quote.csv": "A公司,12000\n".encode()})
                r_text = await blackboard.read_attachment(
                    s, org_a, task_a.id, "quote.csv", store=store
                )
                assert r_text["found"] is True and r_text["is_text"] is True
                assert "12000" in r_text["content"]

                # ④ 二进制类：不读正文，返回元信息提示
                r_bin = await blackboard.read_attachment(s, org_a, task_a.id, "scan.pdf")
                assert r_bin["found"] is True and r_bin["is_text"] is False
                assert "pdf" in r_bin["content"]

                # ⑤ 不存在的附件
                r_missing = await blackboard.read_attachment(s, org_a, task_a.id, "nope.txt")
                assert r_missing["found"] is False

                # ⑥ 经 McpRuntime(ahandler) 工具调用可通
                reg = McpRegistry()
                blackboard.register_blackboard_tools(reg)
                from polis.modules.model.gateway import ToolCall

                rt = McpRuntime(
                    reg,
                    ctx=blackboard.ToolCtx(
                        s, org_a, task_a.id, attachment_task_id=task_a.id, store=store
                    ),
                )
                tc = ToolCall(id="t1", name="read_attachment", arguments={"filename": "quote.csv"})
                parsed = json.loads(await rt.call(tc))
                assert parsed["found"] is True and "12000" in parsed["content"]
        finally:
            await engine.dispose()

    asyncio.run(_run())


def test_resolve_owner_task_id_maps_run_to_task(pg_url: str) -> None:
    org_a, user_a = _make_org_user(pg_url)

    async def _run() -> None:
        engine = create_async_engine(get_settings().database_url)
        try:
            async with async_sessionmaker(engine)() as s:
                task = await planner_repo.create_task(
                    s, org_a, name="T", goal="g", created_by=user_a
                )
                plan = await planner_repo.create_plan(
                    s, org_a, goal="g", dag={"nodes": []}, version="v1", estimated_cost_cents=0
                )
                run = await planner_repo.create_task_run(s, org_a, plan.id, "wf-x", task_id=task.id)
                await s.flush()

                owner = await blackboard.resolve_owner_task_id(s, org_a, run.id)
                assert owner == task.id

                # 无关联 task 的 run → None
                plan2 = await planner_repo.create_plan(
                    s, org_a, goal="g2", dag={"nodes": []}, version="v1", estimated_cost_cents=0
                )
                bare_run = await planner_repo.create_task_run(s, org_a, plan2.id, "wf-y")
                await s.flush()
                assert await blackboard.resolve_owner_task_id(s, org_a, bare_run.id) is None

                # task_run_id 为 None（如未走 task 而是直接 plan run）→ None
                assert await blackboard.resolve_owner_task_id(s, org_a, None) is None
        finally:
            await engine.dispose()

    asyncio.run(_run())


def test_execute_injects_attachment_brief_into_prompt(pg_url: str) -> None:
    """端到端：附件清单真正进了 prompt——用确定性 stub 回显验证影响了产出。"""
    org_a, user_a = _make_org_user(pg_url)
    asyncio.run(seed())

    async def _run() -> None:
        engine = create_async_engine(get_settings().database_url)
        try:
            async with async_sessionmaker(engine)() as s:
                task = await planner_repo.create_task(
                    s, org_a, name="供应商分析", goal="分析报价单", created_by=user_a
                )
                await planner_repo.create_attachment(
                    s,
                    org_a,
                    task_id=task.id,
                    filename="quote.csv",
                    uri=f"s3://polis/{org_a}/{task.id}/quote.csv",
                    mime="text/csv",
                    size=10,
                    field="报价单",
                )
                plan = await planner_repo.create_plan(
                    s, org_a, goal="g", dag={"nodes": []}, version="v1", estimated_cost_cents=0
                )
                run = await planner_repo.create_task_run(
                    s, org_a, plan.id, "wf-e2e", task_id=task.id
                )
                await s.flush()

                from polis.modules.runtime.guardrails import Guardrails
                from polis.modules.runtime.mcp import default_registry

                node = {"id": "n1", "input_hint": "请分析附件报价", "required_capabilities": []}
                result = await agent_runtime.execute(
                    s,
                    node,
                    str(org_a),
                    task_id=str(run.id),
                    goal="分析报价单",
                    gateway=StubModelGateway(),
                    registry=default_registry(),
                    guard=Guardrails(),
                )
                await s.flush()

                assert result["ok"] is True
                # StubModelGateway 回显最后一条 user 消息 → 产出里应能看到附件清单文本
                assert "quote.csv" in (result["output"] or "")
                assert "报价单" in (result["output"] or "")
        finally:
            await engine.dispose()

    asyncio.run(_run())
