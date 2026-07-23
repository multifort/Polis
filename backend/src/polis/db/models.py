"""模型汇总：import 各 module 的 ORM 模型，使 Alembic autogenerate 能发现全部表。

表清单与归类见 docs/design/0b-数据模型总表与扩展策略.md。
"""

from __future__ import annotations

from polis.db.base import Base
from polis.modules.kernel import models as kernel_models
from polis.modules.memory import models as memory_models
from polis.modules.model import models as model_models
from polis.modules.observability import models as observability_models
from polis.modules.org import models as org_models
from polis.modules.planner import models as planner_models
from polis.modules.runtime import models as runtime_models

__all__ = [
    "Base",
    "kernel_models",
    "memory_models",
    "model_models",
    "observability_models",
    "org_models",
    "planner_models",
    "runtime_models",
]
