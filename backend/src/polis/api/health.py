"""健康检查：/health 活性（无依赖）、/ready 就绪（含 DB 可达，TD-006）。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from polis.config import get_settings
from polis.db.session import get_session

router = APIRouter(tags=["meta"])


class Health(BaseModel):
    status: str
    service: str
    env: str
    version: str


class Ready(BaseModel):
    status: str
    db: str


@router.get("/health", response_model=Health)
def health() -> Health:
    s = get_settings()
    return Health(status="ok", service=s.app_name, env=s.env, version=s.version)


@router.get("/ready", response_model=Ready)
async def ready(session: Annotated[AsyncSession, Depends(get_session)]) -> Ready:
    await session.execute(text("SELECT 1"))
    return Ready(status="ok", db="up")
