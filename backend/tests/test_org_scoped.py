"""单元测试：select_org_scoped 应用层 org 过滤助手（TD-015）。纯逻辑，无 DB。"""

from __future__ import annotations

import uuid

from polis.db.org_scoped import select_org_scoped
from polis.modules.planner.models import Plan, TaskRun


def _sql(stmt: object) -> str:
    return str(stmt.compile(compile_kwargs={"literal_binds": True}))  # type: ignore[attr-defined]


def test_select_org_scoped_adds_org_filter() -> None:
    oid = uuid.uuid4()
    sql = _sql(select_org_scoped(Plan, oid))
    assert "plan.org_id" in sql
    assert oid.hex in sql  # UUID 在 SQL 中渲染为无连字符 hex


def test_select_org_scoped_chains_with_extra_where() -> None:
    oid = uuid.uuid4()
    pid = uuid.uuid4()
    stmt = select_org_scoped(TaskRun, oid).where(TaskRun.plan_id == pid)
    sql = _sql(stmt)
    assert "task_run.org_id" in sql
    assert "task_run.plan_id" in sql
