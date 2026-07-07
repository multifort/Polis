"""FastAPI 应用工厂。modular monolith 组合根：lifespan 管引擎、装配各模块路由、CORS。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from polis.api.router import api_router
from polis.config import get_settings
from polis.db.session import dispose_engine, init_engine


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    init_engine()
    yield
    await dispose_engine()


def create_app() -> FastAPI:
    settings = get_settings()
    settings.validate_for_prod()  # 生产类环境下 fail-closed 校验 JWT/CORS/邮件（TD-013）
    app = FastAPI(
        title=settings.app_name,
        version=settings.version,
        summary="Polis — 多 Agent 协同平台后端",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,  # TD-014：前端使用 httpOnly auth cookies；生产 origin 必须显式收紧
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(api_router)
    return app


app = create_app()
