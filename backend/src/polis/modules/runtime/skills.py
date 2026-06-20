"""SkillLoader：技能双形态加载（design 04 §2）。

- 手册型(manual)：SKILL.md 正文注入系统提示词（讲「怎么做」）。
- 工具型(tool)：经 MCP 暴露为可调用函数（讲「用什么做」），按 authority 最小权限过滤。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from polis.modules.model.gateway import ToolSpec
from polis.modules.org.schemas import AgentAuthority
from polis.modules.runtime import repository as repo


@dataclass
class BoundTool:
    """工具型技能的绑定：给模型的 ToolSpec + MCP 路由信息（server/tool）。"""

    spec: ToolSpec
    mcp_server: str
    tool: str


@dataclass
class LoadedSkills:
    system_append: str = ""  # 手册拼接进系统提示词
    tools: list[BoundTool] = field(default_factory=list)


def _parse_ref(ref: str) -> tuple[str, str | None]:
    """'name@version' → (name, version)；'name' → (name, None)。"""
    if "@" in ref:
        name, version = ref.split("@", 1)
        return name, version or None
    return ref, None


async def load_skills(
    session: AsyncSession, skill_refs: list[str], authority: AgentAuthority
) -> LoadedSkills:
    """加载技能引用列表。手册进 system_append；工具按 allowed_tools 过滤后产出 BoundTool。"""
    manuals: list[str] = []
    tools: list[BoundTool] = []
    for ref in skill_refs:
        name, version = _parse_ref(ref)
        found = await repo.get_skill_with_version(session, name, version)
        if found is None:
            continue  # 缺失技能跳过（不阻断；登记可观测留后续）
        skill, sv = found
        if skill.kind == "manual":
            if sv.content:
                manuals.append(sv.content)
        elif skill.kind == "tool":
            tool_name = sv.tool or skill.name
            # 防线2 最小权限：不在 allowed_tools 的工具不加载（design 04 §5）
            if tool_name not in authority.allowed_tools:
                continue
            tools.append(
                BoundTool(
                    spec=ToolSpec(
                        name=tool_name,
                        description=sv.content or skill.name,
                        parameters=sv.io_schema or {},
                    ),
                    mcp_server=sv.mcp_server or "",
                    tool=tool_name,
                )
            )
    return LoadedSkills(system_append="\n\n".join(manuals), tools=tools)
