"""组织级查询助手（TD-015）：在 RLS 之上提供应用层显式 org_id 过滤。

约定（与 ADR-0005「逻辑隔离 + RLS 兜底」配套）：
- 请求内组织级查询：OrgContext 已 `SET app.current_org`，RLS 生效；
  用本助手做**纵深防御**（应用层也显式过滤）。
- 请求外的后台任务/脚本（无 RLS 上下文，如 decay_job/清理）操作组织级表：
  **必须**用本助手，否则会跨租户。
"""

from __future__ import annotations

import uuid

from sqlalchemy import Select, select

from polis.db.mixins import OrgScopedMixin


def select_org_scoped[T: OrgScopedMixin](model: type[T], org_id: uuid.UUID) -> Select[tuple[T]]:
    """生成限定到指定 org 的 select（要求 model 继承 OrgScopedMixin，带 org_id 列）。"""
    return select(model).where(model.org_id == org_id)
