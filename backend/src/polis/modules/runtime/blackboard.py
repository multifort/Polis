"""任务黑板（V2-B1/P2b-2）：节点产出 + 任务附件按需共享，全文懒加载，token 受控。

- 写：节点产出落 `result_envelope`（summary 摘要 + content 全文 + tokens），见 agent_runtime。
- 读（节点产出）：下游默认注入"**直接依赖的摘要**"（确定可靠，修 F3 的"下游看不到上游"）；
  需要某上游**全文**时，Agent 调用内置确定性技能 `read_node_output(node_id)` 懒加载。
- 读（任务附件，P2b-2）：默认注入"**附件清单**"（文件名/类型/字段，便宜）；需要某附件**正文**时，
  Agent 调用内置确定性技能 `read_attachment(filename)` 懒加载（仅文本类；二进制返回元信息提示）。
  附件挂在**可复用任务**(task)上，而节点执行的 task_id 是本次**运行**(task_run)——需先反查
  `task_run.task_id` 才能定位附件所属任务。
设计：docs/design/v2/02 §7、§16；v2/05 §5、§16.2。
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
from polis.modules.storage.deps import ObjectStoreLike

SUMMARY_CHARS = 280
FULL_CHARS = 6000  # read_node_output/read_attachment 全文上限（~4k tokens）；超则截断提示分段

# 附件正文可懒加载读取的类型（文本类）；其余（xlsx/pdf/图片等）仅暴露元信息，不做二进制解析（MVP）。
_TEXT_MIME_PREFIXES = ("text/", "application/json")
_TEXT_EXTS = (".txt", ".md", ".csv", ".json", ".yaml", ".yml", ".log")


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


# ── 任务附件（P2b-2）：默认注入清单，正文按需懒加载 ──────────────────────────────


async def resolve_owner_task_id(
    session: AsyncSession, org_id: uuid.UUID, task_run_id: uuid.UUID | None
) -> uuid.UUID | None:
    """task_run.id（本次运行）→ 所属可复用 task.id（附件挂在任务上，不挂在某次运行上）。"""
    if task_run_id is None:
        return None
    from polis.modules.planner.models import TaskRun

    run = await session.scalar(select_org_scoped(TaskRun, org_id).where(TaskRun.id == task_run_id))
    return run.task_id if run is not None else None


async def attachments_brief(
    session: AsyncSession, org_id: uuid.UUID, owner_task_id: uuid.UUID | None
) -> str:
    """任务附件清单文本（文件名+类型+字段），默认注入下游上下文（便宜、可靠）。"""
    if owner_task_id is None:
        return ""
    from polis.modules.planner import repository as planner_repo

    rows = await planner_repo.list_attachments(session, org_id, owner_task_id)
    if not rows:
        return ""
    lines = ["【任务附件】"]
    for a in rows:
        meta = a.meta or {}
        fname = meta.get("filename") or a.caption or ""
        field = meta.get("field")
        label = f"- {fname}" + (f"（{field}）" if field else "")
        if a.mime:
            label += f" [{a.mime}]"
        lines.append(label)
    lines.append("（需要某附件正文时，调用工具 read_attachment(filename)。）")
    return "\n".join(lines)


def _looks_like_text(filename: str, mime: str | None) -> bool:
    if mime and any(mime.startswith(p) for p in _TEXT_MIME_PREFIXES):
        return True
    return filename.lower().endswith(_TEXT_EXTS)


async def read_attachment(
    session: AsyncSession,
    org_id: uuid.UUID,
    owner_task_id: uuid.UUID | None,
    filename: str,
    store: ObjectStoreLike | None = None,
) -> dict[str, Any]:
    """按文件名读取某任务附件正文（懒加载）。仅文本类；二进制返回元信息提示。"""
    if owner_task_id is None or not filename:
        return {"filename": filename, "found": False, "content": ""}
    from polis.modules.planner import repository as planner_repo

    art = await planner_repo.get_attachment(session, org_id, owner_task_id, filename)
    if art is None:
        return {"filename": filename, "found": False, "content": ""}
    if not _looks_like_text(filename, art.mime):
        return {
            "filename": filename,
            "found": True,
            "is_text": False,
            "content": f"（{art.mime or '未知类型'} 二进制文件，暂不支持直接读取正文；"
            "仅可见文件名/类型等元信息）",
        }
    from polis.modules.storage.client import ObjectStore, StorageError

    try:
        active_store: ObjectStoreLike = store or ObjectStore()
        data = await active_store.get(str(org_id), str(owner_task_id), filename)
    except StorageError as exc:
        return {
            "filename": filename,
            "found": True,
            "is_text": True,
            "content": f"（读取失败：{exc}）",
        }
    text = data.decode("utf-8", errors="replace")
    truncated = len(text) > FULL_CHARS
    return {
        "filename": filename,
        "found": True,
        "is_text": True,
        "content": text[:FULL_CHARS] + ("…（已截断，可分段处理）" if truncated else ""),
    }


# ── 内置确定性技能（黑板取数）：取数=确定性、决策=LLM ──────────────────────────


@dataclass
class ToolCtx:
    """黑板工具执行上下文（请求外，无 RLS，显式 org 过滤）。"""

    session: AsyncSession
    org_id: uuid.UUID
    task_id: uuid.UUID | None  # task_run.id（read_node_output 用：查 result_envelope）
    attachment_task_id: uuid.UUID | None = None  # 可复用 task.id（read_attachment 用：查附件）
    store: ObjectStoreLike | None = None  # 测试可注入假实现；生产留空按需构造


_READ_NODE_SPEC = ToolSpec(
    name="read_node_output",
    description="按节点 id 读取某上游节点的完整产出全文，用于深入引用上游分析。",
    parameters={
        "type": "object",
        "properties": {"node_id": {"type": "string", "description": "上游节点 id，如 n2"}},
        "required": ["node_id"],
    },
)

_READ_ATTACHMENT_SPEC = ToolSpec(
    name="read_attachment",
    description="按文件名读取任务上传附件的正文（仅文本类；二进制返回类型/大小等元信息）。",
    parameters={
        "type": "object",
        "properties": {"filename": {"type": "string", "description": "附件文件名，如 报价单.csv"}},
        "required": ["filename"],
    },
)


def blackboard_specs() -> list[ToolSpec]:
    """暴露给模型的黑板工具 spec（追加到 agent 技能工具之外）。"""
    return [_READ_NODE_SPEC, _READ_ATTACHMENT_SPEC]


def register_blackboard_tools(registry: McpRegistry) -> None:
    """把黑板工具注册进运行时（ctx-aware async handler）。"""

    async def _read_handler(args: dict[str, Any], ctx: ToolCtx) -> str:
        nid = str(args.get("node_id", ""))
        r = await read_node_output(ctx.session, ctx.org_id, ctx.task_id, nid)
        return json.dumps(r, ensure_ascii=False)

    async def _read_attachment_handler(args: dict[str, Any], ctx: ToolCtx) -> str:
        fname = str(args.get("filename", ""))
        r = await read_attachment(
            ctx.session, ctx.org_id, ctx.attachment_task_id, fname, store=ctx.store
        )
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
    registry.register(
        McpTool(
            server="local",
            name="read_attachment",
            description=_READ_ATTACHMENT_SPEC.description,
            parameters=_READ_ATTACHMENT_SPEC.parameters,
            ahandler=_read_attachment_handler,
        )
    )
