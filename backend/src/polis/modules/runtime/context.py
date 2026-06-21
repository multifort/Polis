"""ContextAssembler：运行时注入三样（design 04 §1.2）。

三样 = ①记忆切片(05 RAG) + ②启用技能(手册+工具) + ③模型 + 任务级短时凭证(06)。
M4 中记忆/凭证为桩（ADR-0007），技能/模型解析为真实。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from polis.modules.memory import center as memory_center
from polis.modules.model import credential
from polis.modules.model.credential import ScopedCredential
from polis.modules.model.gateway import ResolvedModel, resolve_model
from polis.modules.org.schemas import AgentConfig
from polis.modules.runtime.skills import LoadedSkills, load_skills

# model 未指定时的桩默认模型（M6 接 LiteLLM 后改为按 catalog 默认/成本择优）
DEFAULT_STUB_MODEL = ResolvedModel(
    id="stub-default", provider="stub", litellm_name=None, context_window=8192
)


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
    config: AgentConfig,
    node: dict[str, Any],
    org_id: uuid.UUID,
    task_id: str,
) -> ExecCtx:
    """组装执行上下文：记忆切片 + 技能 + 模型 + 短时凭证 + 目标。"""
    # 检索 role+org 作用域记忆（M5-C 确定性检索；agent 默认可读这两个作用域）
    slice_ = await memory_center.retrieve(
        session,
        org_id,
        scopes=["role", "org"],
        namespaces=None,
        query=node.get("input_hint") or "",
    )
    memory_slice = slice_.to_text()
    skills = await load_skills(session, config.skills, config.authority)
    model = await resolve_model(session, config.model) if config.model else DEFAULT_STUB_MODEL
    cred = await credential.scoped(session, org_id, model.id, task_id)
    goal = node.get("expected_output") or node.get("input_hint") or ""
    return ExecCtx(
        goal=goal, memory_slice=memory_slice, skills=skills, model=model, cred=cred, node=node
    )
