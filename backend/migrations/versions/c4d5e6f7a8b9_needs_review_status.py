"""V2-S1 质量门：task_run/plan 状态加 needs_review

Revision ID: c4d5e6f7a8b9
Revises: b3c4d5e6f7a8
Create Date: 2026-06-23 10:00:00.000000

关键节点产出经 Evaluator 不达标 → 节点 needs_rework → 顶层 needs_review（区别于真正的 failed）。
约束逻辑名为 "status"，命名约定 ck_%(table_name)s_%(constraint_name)s → 实际 ck_<table>_status。
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "c4d5e6f7a8b9"
down_revision: str | None = "b3c4d5e6f7a8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("status", "task_run", type_="check")
    op.create_check_constraint(
        "status",
        "task_run",
        "status IN ('pending','running','paused','done','failed','needs_review')",
    )
    op.drop_constraint("status", "plan", type_="check")
    op.create_check_constraint(
        "status",
        "plan",
        "status IN ('draft','approved','running','done','failed','needs_review')",
    )


def downgrade() -> None:
    op.drop_constraint("status", "task_run", type_="check")
    op.create_check_constraint(
        "status",
        "task_run",
        "status IN ('pending','running','paused','done','failed')",
    )
    op.drop_constraint("status", "plan", type_="check")
    op.create_check_constraint(
        "status",
        "plan",
        "status IN ('draft','approved','running','done','failed')",
    )
