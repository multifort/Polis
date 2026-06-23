"""组织级查询助手（TD-015）：在 RLS 之上提供应用层显式 org_id 过滤。

约定（与 ADR-0005「逻辑隔离 + RLS 兜底」配套）：
- 请求内组织级查询：OrgContext 已 `SET app.current_org`，RLS 生效；
  用本助手做**纵深防御**（应用层也显式过滤）。
- 请求外的后台任务/脚本（无 RLS 上下文，如 decay_job/清理）操作组织级表：
  **必须**用本助手，否则会跨租户。
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import ColumnElement, Select, or_, select

from polis.db.mixins import OrgScopedMixin


def select_org_scoped[T: OrgScopedMixin](model: type[T], org_id: uuid.UUID) -> Select[tuple[T]]:
    """生成限定到指定 org 的 select（要求 model 继承 OrgScopedMixin，带 org_id 列）。"""
    return select(model).where(model.org_id == org_id)


def visible_clause(model: Any, org_id: uuid.UUID) -> ColumnElement[bool]:
    """全局共享目录（skill/plan_template/role_template…）的**可见性过滤**（V2-R1）。

    可见集 = 自己私有(owner_org_id=org) ∪ 公共(visibility='public')；绝不见他 org 私有。
    要求 model 带 owner_org_id + visibility 列。**写**仍须严格按属主，本助手只用于读。
    """
    return or_(model.owner_org_id == org_id, model.visibility == "public")


def select_visible(model: Any, org_id: uuid.UUID) -> Select[Any]:
    """生成"自己私有 ∪ 公共"的 select（语义检索/复用前的可见性过滤）。"""
    return select(model).where(visible_clause(model, org_id))
