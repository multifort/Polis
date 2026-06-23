"""V2-P1 任务实体：task 表（可复用）+ task_run.task_id + task RLS

Revision ID: b3c4d5e6f7a8
Revises: a2b3c4d5e6f7
Create Date: 2026-06-22 23:00:00.000000

task = 可复用工作项（name/goal/scenario_ref/input_schema/inputs）；plan 退为某次运行的 DAG 快照；
task_run.task_id 关联任务（1 任务:N 执行记录，nullable 兼容旧/临时运行）。task 为组织级表 → 启用 RLS。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "b3c4d5e6f7a8"
down_revision: str | None = "a2b3c4d5e6f7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "task",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column(
            "org_id",
            sa.Uuid(),
            sa.ForeignKey("org.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "scenario_ref", sa.Text(), nullable=True
        ),  # 场景模板引用（plan_template 名，nullable）
        sa.Column("goal", sa.Text(), nullable=False),
        sa.Column("input_schema", JSONB(), nullable=True),
        sa.Column("inputs", JSONB(), nullable=True),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("app_user.id"), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_task_org_id", "task", ["org_id"])

    op.add_column(
        "task_run", sa.Column("task_id", sa.Uuid(), sa.ForeignKey("task.id"), nullable=True)
    )

    # 组织级表 → RLS（与 m1/harden 同策略：fail-closed，仅当前 org 可见）
    op.execute("ALTER TABLE task ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE task FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY org_isolation ON task "
        "USING (org_id = NULLIF(current_setting('app.current_org', true), '')::uuid)"
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS org_isolation ON task")
    op.drop_column("task_run", "task_id")
    op.drop_index("ix_task_org_id", table_name="task")
    op.drop_table("task")
