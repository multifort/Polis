"""聚合各模块路由的根路由器。新模块在此挂载自己的 router。"""

from __future__ import annotations

from fastapi import APIRouter

from polis.api import health

api_router = APIRouter()
api_router.include_router(health.router)
