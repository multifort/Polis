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
from polis.modules.runtime.mcp import McpRegistry, McpTool


@dataclass
class BoundTool:
    """工具型技能的绑定：给模型的 ToolSpec + MCP 路由信息（server/tool）。"""

    spec: ToolSpec
    mcp_server: str
    tool: str
    http_endpoint: str | None = None
    http_headers: dict[str, str] = field(default_factory=dict)
    timeout_seconds: float = 5.0
    mcp_transport: str | None = None
    mcp_url: str | None = None
    mcp_command: str | None = None
    mcp_args: list[str] = field(default_factory=list)
    mcp_env: dict[str, str] = field(default_factory=dict)
    sse_read_timeout_seconds: float | None = None


@dataclass
class LoadedSkills:
    system_append: str = ""  # 手册拼接进系统提示词
    tools: list[BoundTool] = field(default_factory=list)


@dataclass(frozen=True)
class McpSdkConfig:
    transport: str
    url: str | None = None
    command: str | None = None
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    timeout_seconds: float = 5.0
    sse_read_timeout_seconds: float | None = None


def _parse_ref(ref: str) -> tuple[str, str | None]:
    """'name@version' → (name, version)；'name' → (name, None)。"""
    if "@" in ref:
        name, version = ref.split("@", 1)
        return name, version or None
    return ref, None


def _http_bridge_config(permissions: dict[str, object] | None) -> tuple[str | None, float]:
    http = (permissions or {}).get("http")
    if not isinstance(http, dict):
        return None, 5.0
    endpoint = http.get("endpoint")
    timeout = http.get("timeout_seconds")
    timeout_seconds = float(timeout) if isinstance(timeout, int | float) else 5.0
    return (endpoint if isinstance(endpoint, str) and endpoint else None), timeout_seconds


def _mcp_sdk_config(permissions: dict[str, object] | None) -> McpSdkConfig | None:
    mcp = (permissions or {}).get("mcp")
    if not isinstance(mcp, dict):
        return None

    transport = mcp.get("transport")
    if transport not in {"stdio", "sse", "streamable_http"}:
        return None

    args = mcp.get("args")
    env = mcp.get("env")
    timeout = mcp.get("timeout_seconds")
    sse_read_timeout = mcp.get("sse_read_timeout_seconds")
    return McpSdkConfig(
        transport=transport,
        url=mcp.get("url") if isinstance(mcp.get("url"), str) else None,
        command=mcp.get("command") if isinstance(mcp.get("command"), str) else None,
        args=[str(arg) for arg in args] if isinstance(args, list) else [],
        env={str(k): str(v) for k, v in env.items()} if isinstance(env, dict) else {},
        timeout_seconds=float(timeout) if isinstance(timeout, int | float) else 5.0,
        sse_read_timeout_seconds=(
            float(sse_read_timeout) if isinstance(sse_read_timeout, int | float) else None
        ),
    )


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
            http_endpoint, timeout_seconds = _http_bridge_config(sv.permissions)
            mcp_config = _mcp_sdk_config(sv.permissions)
            tools.append(
                BoundTool(
                    spec=ToolSpec(
                        name=tool_name,
                        description=sv.content or skill.name,
                        parameters=sv.io_schema or {},
                    ),
                    mcp_server=sv.mcp_server or "",
                    tool=tool_name,
                    http_endpoint=http_endpoint,
                    timeout_seconds=mcp_config.timeout_seconds
                    if mcp_config is not None
                    else timeout_seconds,
                    mcp_transport=mcp_config.transport if mcp_config is not None else None,
                    mcp_url=mcp_config.url if mcp_config is not None else None,
                    mcp_command=mcp_config.command if mcp_config is not None else None,
                    mcp_args=mcp_config.args if mcp_config is not None else [],
                    mcp_env=mcp_config.env if mcp_config is not None else {},
                    sse_read_timeout_seconds=mcp_config.sse_read_timeout_seconds
                    if mcp_config is not None
                    else None,
                )
            )
    return LoadedSkills(system_append="\n\n".join(manuals), tools=tools)


def register_bound_tools(registry: McpRegistry, loaded: LoadedSkills) -> None:
    """把 SkillVersion 声明的外部工具注册进运行时 registry。"""
    for bound in loaded.tools:
        if bound.http_endpoint is None and bound.mcp_transport is None:
            continue
        registry.register(
            McpTool(
                server=bound.mcp_server,
                name=bound.tool,
                description=bound.spec.description,
                parameters=bound.spec.parameters,
                http_endpoint=bound.http_endpoint,
                http_headers=bound.http_headers,
                timeout_seconds=bound.timeout_seconds,
                mcp_transport=bound.mcp_transport,
                mcp_url=bound.mcp_url,
                mcp_command=bound.mcp_command,
                mcp_args=bound.mcp_args,
                mcp_env=bound.mcp_env,
                sse_read_timeout_seconds=bound.sse_read_timeout_seconds,
            )
        )
