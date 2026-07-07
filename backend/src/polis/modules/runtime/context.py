"""ContextAssembler：运行时注入三样（design 04 §1.2）。

三样 = ①记忆切片(05 RAG) + ②启用技能(手册+工具) + ③模型 + 任务级短时凭证(06)。
M4 中记忆/凭证为桩（ADR-0007），技能/模型解析为真实。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from polis.config import get_settings
from polis.modules.memory import center as memory_center
from polis.modules.model import credential
from polis.modules.model.credential import ScopedCredential
from polis.modules.model.gateway import ModelGateway, ResolvedModel, resolve_model
from polis.modules.org import repository as org_repo
from polis.modules.org.schemas import AgentConfig
from polis.modules.runtime.skills import LoadedSkills, load_skills


@dataclass
class ExecCtx:
    goal: str
    memory_slice: str
    skills: LoadedSkills
    model: ResolvedModel
    cred: ScopedCredential
    node: dict[str, Any]
    deps_brief: str = ""  # 直接依赖的上游产出摘要（V2-B1 黑板，默认注入下游）
    attachments_brief: str = ""  # 任务附件清单（P2b-2，默认注入；正文经 read_attachment 懒加载）


async def build(
    session: AsyncSession,
    gateway: ModelGateway,
    config: AgentConfig,
    node: dict[str, Any],
    org_id: uuid.UUID,
    task_id: str,
    goal: str | None = None,
) -> ExecCtx:
    """组装执行上下文：记忆切片 + 技能 + 模型 + 短时凭证 + 目标。

    goal 为**用户意图**（F3：贯通后让产出锚定目标），优先于节点静态 expected_output；
    检索记忆时也并入 goal，召回更贴合本次任务。
    """
    # 检索 role+org 作用域记忆。embedding 可用时走向量 RAG，否则确定性关键词（M5-C/M6-D）
    node_hint = node.get("input_hint") or ""
    query = f"{goal} {node_hint}".strip() if goal else node_hint
    query_embedding = (await gateway.embed([query]))[0] if query else None
    slice_ = await memory_center.retrieve(
        session,
        org_id,
        scopes=["role", "org"],
        namespaces=None,
        query=query,
        query_embedding=query_embedding,
        gateway=gateway,
    )
    memory_slice = slice_.to_text()
    skills = await load_skills(session, config.skills, config.authority)
    # fallback 顺序：Agent 显式模型 → 公司主模型 → 系统默认 chat 模型
    model_id = (
        config.model
        or await org_repo.get_org_primary_model_id(session, org_id)
        or get_settings().default_chat_model
    )
    model = await resolve_model(session, model_id)
    cred = await credential.scoped(session, org_id, model.id, task_id)
    # 目标优先用用户意图；回退节点静态 expected_output/input_hint
    eff_goal = goal or node.get("expected_output") or node.get("input_hint") or ""
    return ExecCtx(
        goal=eff_goal, memory_slice=memory_slice, skills=skills, model=model, cred=cred, node=node
    )
