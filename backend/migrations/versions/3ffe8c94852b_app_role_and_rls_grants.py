"""app role and rls grants

Revision ID: 3ffe8c94852b
Revises: f968dc6adc21
Create Date: 2026-06-18 15:17:37.115144
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "3ffe8c94852b"
down_revision: str | None = "f968dc6adc21"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 非 superuser、NOLOGIN 应用角色：业务连接登录后 SET ROLE polis_app，使 RLS 强制生效。
    # NOLOGIN + 无密码 → 不需任何密钥入库（09§5 / ADR-0005）。
    op.execute(
        "DO $$ BEGIN "
        "IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='polis_app') THEN "
        "CREATE ROLE polis_app NOLOGIN; END IF; END $$;"
    )
    op.execute("GRANT USAGE ON SCHEMA public TO polis_app")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO polis_app")
    op.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO polis_app")
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO polis_app"
    )
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO polis_app"
    )


def downgrade() -> None:
    op.execute(
        "DO $$ BEGIN "
        "IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='polis_app') THEN "
        "EXECUTE 'ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM polis_app'; "
        "EXECUTE 'ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON SEQUENCES FROM polis_app'; "
        "EXECUTE 'DROP OWNED BY polis_app'; "
        "EXECUTE 'DROP ROLE polis_app'; "
        "END IF; END $$;"
    )
