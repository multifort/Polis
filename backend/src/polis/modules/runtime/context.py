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


async def build(
    session: AsyncSession,
    gateway: ModelGateway,
    config: AgentConfig,
    node: dict[str, Any],
    org_id: uuid.UUID,
    task_id: str,
) -> ExecCtx:
    """组装执行上下文：记忆切片 + 技能 + 模型 + 短时凭证 + 目标。"""
    # 检索 role+org 作用域记忆。embedding 可用时走向量 RAG，否则确定性关键词（M5-C/M6-D）
    query = node.get("input_hint") or ""
    query_embedding = (await gateway.embed([query]))[0] if query else None
    slice_ = await memory_center.retrieve(
        session,
        org_id,
        scopes=["role", "org"],
        namespaces=None,
        query=query,
        query_embedding=query_embedding,
    )
    memory_slice = slice_.to_text()
    skills = await load_skills(session, config.skills, config.authority)
    # agent 未指定 model 时回退到系统默认 chat 模型（M6：真实模型，非桩）
    model = await resolve_model(session, config.model or get_settings().default_chat_model)
    cred = await credential.scoped(session, org_id, model.id, task_id)
    goal = node.get("expected_output") or node.get("input_hint") or ""
    return ExecCtx(
        goal=goal, memory_slice=memory_slice, skills=skills, model=model, cred=cred, node=node
    )
