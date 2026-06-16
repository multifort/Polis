"""健康检查端点（T0.1 验收：/health 返回 ok）。"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from polis.config import get_settings

router = APIRouter(tags=["meta"])


class Health(BaseModel):
    status: str
    service: str
    env: str
    version: str


@router.get("/health", response_model=Health)
def health() -> Health:
    s = get_settings()
    return Health(status="ok", service=s.app_name, env=s.env, version=s.version)
