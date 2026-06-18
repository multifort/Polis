"""harden rls policies nullif

Revision ID: 38f12a115426
Revises: 3ffe8c94852b
Create Date: 2026-06-18 20:59:01.278341
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "38f12a115426"
down_revision: str | None = "3ffe8c94852b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


RLS_TABLES = (
    "role",
    "agent",
    "agent_version",
    "agent_capability",
    "org_enabled_skill",
    "memory",
    "result_envelope",
    "artifact_descriptor",
    "skill_invocation",
    "task_run",
    "plan",
    "run_manifest",
    "approval",
    "trace_ref",
)


def upgrade() -> None:
    # 用 NULLIF 把空串归 NULL：app.current_org 被 set 后 RESET 会变 ""，
    # 旧策略 ''::uuid 会报错；改后空串/未设均 fail-closed 返回 0 行，不报错。
    for t in RLS_TABLES:
        op.execute(f"DROP POLICY IF EXISTS org_isolation ON {t}")
        op.execute(
            f"CREATE POLICY org_isolation ON {t} "
            "USING (org_id = NULLIF(current_setting('app.current_org', true), '')::uuid)"
        )


def downgrade() -> None:
    for t in RLS_TABLES:
        op.execute(f"DROP POLICY IF EXISTS org_isolation ON {t}")
        op.execute(
            f"CREATE POLICY org_isolation ON {t} "
            "USING (org_id = current_setting('app.current_org', true)::uuid)"
        )
