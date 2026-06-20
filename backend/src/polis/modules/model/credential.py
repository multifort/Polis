"""CredentialBroker（design 06 §2）。

M4 桩（ADR-0007）：返回占位短时句柄，无真实 Key。
M6 换信封加密：解密 BYO-Key → 任务级短时句柄 → 用完即焚 + 审计。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass
class ScopedCredential:
    """任务级短时凭证句柄。M4 桩无真实密钥；永不落盘/日志（design 06）。"""

    handle: str
    model_id: str
    task_id: str


def scoped(org_id: uuid.UUID, model_id: str, task_id: str) -> ScopedCredential:
    """签发任务级短时凭证句柄（M4 桩）。"""
    return ScopedCredential(handle=f"stub-cred:{task_id}", model_id=model_id, task_id=task_id)
