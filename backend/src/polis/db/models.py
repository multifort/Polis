"""模型汇总：在此 import 各 module 的 ORM 模型，使 Alembic autogenerate 能发现全部表。

目前为空基线（M1 起逐步引入 org/agent/plan/memory… 模型，见 docs/design/02-09）。
"""

from __future__ import annotations

from polis.db.base import Base

__all__ = ["Base"]
