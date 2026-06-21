"""memory API schema（治理浏览/删除）。"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class MemoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    scope: str
    namespace: str
    type: str
    content: str
    importance: float
    confidence: float
    provenance: dict[str, Any] | None = None
    created_at: datetime
