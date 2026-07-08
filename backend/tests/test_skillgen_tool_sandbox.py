"""单元测试（TD-032）：tool-skill 最小权限沙箱闸，不依赖 DB/Docker。"""

from __future__ import annotations

import asyncio

import pytest

from polis.modules.planner.skillgen import (
    ToolSkillSandboxError,
    _sandbox_tool_call,
    _validate_tool_permissions,
)
from polis.modules.runtime.mcp import default_registry


def test_tool_permissions_are_normalized_to_least_privilege() -> None:
    perms = _validate_tool_permissions("echo", {"effects": "read"})

    assert perms["effects"] == "read"
    assert perms["requires_credentials"] is False
    assert perms["network"] is False
    assert perms["filesystem"] == "none"
    assert perms["allowed_tools"] == ["echo"]


def test_tool_permissions_allow_http_bridge_network_only_with_endpoint() -> None:
    perms = _validate_tool_permissions(
        "web_search",
        {"effects": "read", "network": "http_tool_bridge"},
        http_endpoint="http://tools.local/mcp",
    )

    assert perms["network"] == "http_tool_bridge"
    assert perms["allowed_tools"] == ["web_search"]


@pytest.mark.parametrize(
    "permissions",
    [
        {"effects": "write"},
        {"requires_credentials": True},
        {"network": True},
        {"filesystem": "write"},
        {"allowed_tools": ["echo", "calc_add"]},
    ],
)
def test_tool_permissions_block_overreach(permissions: dict[str, object]) -> None:
    with pytest.raises(ToolSkillSandboxError):
        _validate_tool_permissions("echo", permissions)


def test_tool_sandbox_calls_registered_local_tool() -> None:
    out = asyncio.run(
        _sandbox_tool_call(
            default_registry(),
            mcp_server="local",
            tool="echo",
            sandbox_args={"text": "ok"},
        )
    )

    assert out == "ok"


def test_tool_sandbox_rejects_unknown_tool() -> None:
    with pytest.raises(ToolSkillSandboxError):
        asyncio.run(
            _sandbox_tool_call(
                default_registry(),
                mcp_server="local",
                tool="missing_tool",
                sandbox_args={},
            )
        )
