"""planner API 路由：模板优先出图（POST /api/plans）。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from polis.db.session import get_session
from polis.modules.org.deps import CurrentOrg
from polis.modules.planner import service
from polis.modules.planner.schemas import PlanCreateIn, PlanResult

router = APIRouter(prefix="/api", tags=["planner"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


@router.post("/plans", response_model=PlanResult, status_code=status.HTTP_201_CREATED)
async def create_plan(data: PlanCreateIn, org: CurrentOrg, session: SessionDep) -> PlanResult:
    # CurrentOrg 已校验成员 + 切到 RLS 上下文
    try:
        return await service.plan(session, org.org_id, data.goal)
    except service.NoTemplateMatch as exc:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "没有可用的计划模板（当前公司能力不足以匹配任何模板）"
        ) from exc
    except service.PlanInvalid as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail={"errors": exc.errors}
        ) from exc
