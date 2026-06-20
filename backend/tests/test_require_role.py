"""单元测试：require_role 路由守卫（09 §6 权限矩阵）。纯逻辑，无 DB。

M3 收尾补：approve/signal 等治理动作需 owner/approver；member 应被 403。
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from fastapi import HTTPException

from polis.modules.org.deps import OrgContext, require_role


def _ctx(role: str) -> OrgContext:
    return OrgContext(org_id=uuid.uuid4(), role=role)


def test_owner_allowed() -> None:
    dep = require_role("owner", "approver")
    ctx = _ctx("owner")
    assert asyncio.run(dep(ctx)) is ctx


def test_approver_allowed() -> None:
    dep = require_role("owner", "approver")
    ctx = _ctx("approver")
    assert asyncio.run(dep(ctx)) is ctx


def test_member_forbidden() -> None:
    dep = require_role("owner", "approver")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(dep(_ctx("member")))
    assert exc.value.status_code == 403
