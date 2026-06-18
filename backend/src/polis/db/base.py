"""声明式 Base + 命名规范。所有 ORM 模型继承 Base；Alembic 以 Base.metadata 为迁移目标。

模型在各 module 的 models.py 定义后，需在 `polis.db.models` 汇总 import，确保 autogenerate 能发现。
"""

from __future__ import annotations

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

# 统一约束/索引命名，保证迁移可读、downgrade 稳定（12 C 系列）
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
