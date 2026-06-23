"""任务黑板（V2-B1）：节点产出按需共享，下游确定性拿到上游，全文懒加载，token 受控。

- 写：节点产出落 `result_envelope`（summary 摘要 + content 全文 + tokens），见 agent_runtime。
- 读：下游默认注入"**直接依赖的摘要**"（确定可靠，修 F3 的"下游看不到上游"）；
  需要某上游**全文**时，Agent 调用内置确定性技能 `read_node_output(node_id)` 懒加载。
设计：docs/design/v2/02 §7、§16。
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from polis.db.org_scoped import select_org_scoped
from polis.modules.memory.models import ResultEnvelope
from polis.modules.model.gateway import ToolSpec
from polis.modules.runtime.mcp import McpRegistry, McpTool

SUMMARY_CHARS = 280
FULL_CHARS = 6000  # read_node_output 全文上限（~4k tokens）；超则截断提示分段


def rough_tokens(text: str | None) -> int:
    """粗略 token 估算（中英混合，约 chars/2）。预算治理用，非精确。"""
    return max(1, len(text or "") // 2)


def summarize(content: str | None) -> str:
    """确定性摘要：压平换行后取首段/截断（M5 简化版，后续可换 LLM 摘要）。"""
    s = " ".join((content or "").split())
    return s if len(s) <= SUMMARY_CHARS else s[:SUMMARY_CHARS] + "…"


async def fetch_dep_envelopes(
    session: AsyncSession, org_id: uuid.UUID, task_id: uuid.UUID | None, node_ids: list[str]
) -> list[ResultEnvelope]:
    if task_id is None or not node_ids:
        return []
    q = (
        select_org_scoped(ResultEnvelope, org_id)
        .where(ResultEnvelope.task_id == task_id, ResultEnvelope.node_id.in_(node_ids))
        .order_by(ResultEnvelope.created_at)
    )
    return list((await session.scalars(q)).all())


async def dep_briefs(
    session: AsyncSession, org_id: uuid.UUID, task_id: uuid.UUID | None, node_ids: list[str]
) -> str:
    """直接依赖的"节点 + 摘要"文本，默认注入下游上下文（便宜、可靠，不推全文）。"""
    envs = await fetch_dep_envelopes(session, org_id, task_id, node_ids)
    if not envs:
        return ""
    lines = ["【上游产出摘要】"]
    for e in envs:
        lines.append(f"- {e.node_id}：{e.summary or summarize(e.content)}")
    lines.append("（需要某上游完整内容时，调用工具 read_node_output(node_id)。）")
    return "\n".join(lines)


async def read_node_output(
    session: AsyncSession, org_id: uuid.UUID, task_id: uuid.UUID | None, node_id: str
) -> dict[str, Any]:
    """按 id 取某上游节点全文（懒加载）。超长截断并提示可分段取。"""
    if task_id is None or not node_id:
        return {"node_id": node_id, "found": False, "content": ""}
    q = (
        select_org_scoped(ResultEnvelope, org_id)
        .where(ResultEnvelope.task_id == task_id, ResultEnvelope.node_id == node_id)
        .order_by(ResultEnvelope.created_at.desc())
    )
    env: ResultEnvelope | None = await session.scalar(q.limit(1))
    if env is None:
        return {"node_id": node_id, "found": False, "content": ""}
    content = env.content or env.summary or ""
    truncated = len(content) > FULL_CHARS
    return {
        "node_id": node_id,
        "found": True,
        "summary": env.summary,
        "content": content[:FULL_CHARS] + ("…（已截断，可分段取）" if truncated else ""),
    }


# ── 内置确定性技能（黑板取数）：取数=确定性、决策=LLM ──────────────────────────


@dataclass
class ToolCtx:
    """黑板工具执行上下文（请求外，无 RLS，显式 org 过滤）。"""

    session: AsyncSession
    org_id: uuid.UUID
    task_id: uuid.UUID | None


_READ_NODE_SPEC = ToolSpec(
    name="read_node_output",
    description="按节点 id 读取某上游节点的完整产出全文，用于深入引用上游分析。",
    parameters={
        "type": "object",
        "properties": {"node_id": {"type": "string", "description": "上游节点 id，如 n2"}},
        "required": ["node_id"],
    },
)


def blackboard_specs() -> list[ToolSpec]:
    """暴露给模型的黑板工具 spec（追加到 agent 技能工具之外）。"""
    return [_READ_NODE_SPEC]


def register_blackboard_tools(registry: McpRegistry) -> None:
    """把黑板工具注册进运行时（ctx-aware async handler）。"""

    async def _read_handler(args: dict[str, Any], ctx: ToolCtx) -> str:
        nid = str(args.get("node_id", ""))
        r = await read_node_output(ctx.session, ctx.org_id, ctx.task_id, nid)
        return json.dumps(r, ensure_ascii=False)

    registry.register(
        McpTool(
            server="local",
            name="read_node_output",
            description=_READ_NODE_SPEC.description,
            parameters=_READ_NODE_SPEC.parameters,
            ahandler=_read_handler,
        )
    )
