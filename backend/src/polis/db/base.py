"""声明式 Base：所有 ORM 模型继承它；Alembic 以 Base.metadata 为迁移目标。

模型在各 module 内定义后，需在 `polis.db.models` 汇总 import，确保 autogenerate 能发现。
"""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
