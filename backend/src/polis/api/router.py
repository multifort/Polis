"""聚合各模块路由的根路由器。新模块在此挂载自己的 router。"""

from __future__ import annotations

from fastapi import APIRouter

from polis.api import catalog, health
from polis.modules.memory import api as memory_api
from polis.modules.model import api as model_api
from polis.modules.org import api as org_api
from polis.modules.planner import api as planner_api

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(org_api.router)
api_router.include_router(planner_api.router)
api_router.include_router(memory_api.router)
api_router.include_router(model_api.router)
api_router.include_router(catalog.router)
