"""FastAPI 应用工厂。modular monolith 的组合根：装配各模块路由。"""

from __future__ import annotations

from fastapi import FastAPI

from polis.api.router import api_router
from polis.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version=settings.version,
        summary="Polis — 多 Agent 协同平台后端",
    )
    app.include_router(api_router)
    return app


app = create_app()
