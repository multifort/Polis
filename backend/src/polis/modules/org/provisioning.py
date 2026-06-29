"""立邦：模板优先的确定性编配（ADR-0006，无 LLM）。

选预设（精确名 / 关键词匹配）→ 实例化 role + agent + agent_version + agent_capability。
预设受信 → Agent 直接 active。LLM 意图解析/缺口生成留 M6。
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from polis.modules.model.gateway import ModelGateway
from polis.modules.observability.audit import write_audit
from polis.modules.org import repository as repo
from polis.modules.org.models import Agent, AgentCapability, AgentVersion, Role, ScenarioPreset
from polis.modules.org.schemas import (
    AgentConfig,
    OrgOut,
    ProvisionedAgentOut,
    ProvisionIn,
    ProvisionOut,
)

logger = logging.getLogger(__name__)


class NoPresetMatch(Exception):
    """没有匹配到任何预设。"""


_TAU_PRESET = 0.45  # 预设语义命中阈值（bge-zh：同域~0.5-0.7/跨域~0.35-0.41，留余量）；按数据校准


def _score(preset: ScenarioPreset, keyword: str) -> int:
    hay = " ".join(
        [preset.name or "", preset.description or "", " ".join(preset.required_capabilities or [])]
    ).lower()
    return sum(1 for tok in keyword.lower().split() if tok and tok in hay)


async def _semantic_preset(
    session: AsyncSession, keyword: str, gateway: ModelGateway
) -> ScenarioPreset | None:
    """TD-017：按 keyword 向量与 preset.embedding 余弦选最相近预设（≥τ 才算命中）。失败→None。"""
    try:
        vec = (await gateway.embed([keyword]))[0]
    except Exception:
        logger.warning("preset 语义匹配 embedding 失败，回退关键词", exc_info=True)
        return None
    if vec is None:
        return None
    ranked = await repo.rank_presets_by_vector(session, vec, limit=1)
    if ranked and ranked[0][1] >= _TAU_PRESET:
        return ranked[0][0]
    return None


async def match_preset(
    session: AsyncSession, data: ProvisionIn, gateway: ModelGateway | None = None
) -> ScenarioPreset | None:
    if data.preset:
        return await repo.get_preset_by_name(session, data.preset)
    if data.keyword:
        # 语义优先（TD-017）：命中即用；未命中/无网关 → 关键词子串兜底（中文弱但确定）
        if gateway is not None:
            hit = await _semantic_preset(session, data.keyword, gateway)
            if hit is not None:
                return hit
        scored = [(p, _score(p, data.keyword)) for p in await repo.list_presets(session)]
        hits = [x for x in scored if x[1] > 0]
        return max(hits, key=lambda x: x[1])[0] if hits else None
    return None


async def provision(
    session: AsyncSession,
    user_id: uuid.UUID,
    data: ProvisionIn,
    gateway: ModelGateway | None = None,
) -> ProvisionOut:
    preset = await match_preset(session, data, gateway)
    if preset is None:
        raise NoPresetMatch
    charter = data.description or preset.description
    org = await repo.create_org_with_owner(session, data.name, charter, user_id)

    templates: list[dict[str, Any]] = (preset.config or {}).get("agentTemplates", [])
    agents_out: list[ProvisionedAgentOut] = []
    for tpl in templates:
        role = Role(org_id=org.id, name=tpl["roleName"])
        session.add(role)
        await session.flush()

        cfg = AgentConfig(
            prompt=tpl.get("promptSkeleton") or tpl["agentName"],
            capabilities=tpl.get("capabilities", []),
            skills=tpl.get("skills", []),
        )
        agent = Agent(
            org_id=org.id,
            role_id=role.id,
            name=tpl["agentName"],
            source="preset",
            status="active",  # 预设受信，直接 active（ADR-0006）
            current_version="v1",
        )
        session.add(agent)
        await session.flush()

        session.add(
            AgentVersion(
                org_id=org.id,
                agent_id=agent.id,
                version="v1",
                config=cfg.model_dump(),
                status="published",
            )
        )
        for cap in cfg.capabilities:
            session.add(AgentCapability(org_id=org.id, agent_id=agent.id, capability=cap))
        agents_out.append(
            ProvisionedAgentOut(
                name=agent.name,
                role_name=role.name,
                status=agent.status,
                capabilities=cfg.capabilities,
            )
        )

    await session.flush()
    await write_audit(
        session,
        action="org.provision",
        actor=str(user_id),
        org_id=org.id,
        target=str(org.id),
        detail={"preset": preset.name, "agents": len(agents_out)},
    )
    return ProvisionOut(
        org=OrgOut(id=org.id, name=org.name, role="owner", description=org.charter),
        preset=f"{preset.name}@{preset.version}",
        agents=agents_out,
    )
