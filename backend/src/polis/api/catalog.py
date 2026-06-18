"""目录只读 API：能力词表 / 模型目录 / 场景预设（公开参考数据）。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from polis.db.session import get_session
from polis.modules.model.models import ModelCatalog
from polis.modules.org.models import ScenarioPreset
from polis.modules.planner.models import Capability

router = APIRouter(prefix="/api/catalog", tags=["catalog"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


class CapabilityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    key: str
    domain: str | None = None
    name: str | None = None
    description: str | None = None


class ModelOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    provider: str | None = None
    litellm_name: str | None = None
    capabilities: list[str] | None = None


class PresetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    name: str
    version: str
    description: str | None = None
    required_capabilities: list[str] | None = None


@router.get("/capabilities", response_model=list[CapabilityOut])
async def list_capabilities(session: SessionDep) -> list[Capability]:
    return list((await session.scalars(select(Capability).order_by(Capability.key))).all())


@router.get("/models", response_model=list[ModelOut])
async def list_models(session: SessionDep) -> list[ModelCatalog]:
    return list((await session.scalars(select(ModelCatalog).order_by(ModelCatalog.id))).all())


@router.get("/presets", response_model=list[PresetOut])
async def list_presets(session: SessionDep) -> list[ScenarioPreset]:
    return list((await session.scalars(select(ScenarioPreset).order_by(ScenarioPreset.name))).all())
