"""org 模块 API 依赖：从 access JWT 解析当前用户。"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from polis.core.security import decode_token

_bearer = HTTPBearer(auto_error=False)


def get_current_user_id(
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> uuid.UUID:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "缺少访问令牌")
    try:
        payload = decode_token(creds.credentials)
    except Exception as exc:  # noqa: BLE001 - 任何解码失败都视为未授权
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "令牌无效或已过期") from exc
    if payload.get("type") != "access":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "令牌类型错误")
    return uuid.UUID(payload["sub"])


CurrentUserId = Annotated[uuid.UUID, Depends(get_current_user_id)]
