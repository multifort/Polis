"""memory 治理 API（design 05 §8/§9）：浏览 + 删除（权限校验 + 审计 + org 隔离）。"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from polis.db.session import get_session
from polis.modules.memory import repository as repo
from polis.modules.memory.schemas import MemoryOut
from polis.modules.observability.audit import write_audit
from polis.modules.org.deps import CurrentOrg, CurrentUserId, OrgContext, require_role

router = APIRouter(prefix="/api", tags=["memory"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
# 治理删除属敏感操作：限 owner/approver
ApproverOrg = Annotated[OrgContext, Depends(require_role("owner", "approver"))]


@router.get("/orgs/current/memory", response_model=list[MemoryOut])
async def list_memory(org: CurrentOrg, session: SessionDep) -> list[MemoryOut]:
    rows = await repo.list_for_org(session, org.org_id)
    return [MemoryOut.model_validate(m) for m in rows]


@router.delete("/memory/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_memory(
    memory_id: uuid.UUID, org: ApproverOrg, user_id: CurrentUserId, session: SessionDep
) -> None:
    """治理删除一条记忆（org 隔离 + 审计）。"""
    mem = await repo.get_by_id(session, org.org_id, memory_id)
    if mem is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "记忆不存在")
    await repo.delete_memory(session, mem)
    await write_audit(
        session,
        action="memory.delete",
        actor=str(user_id),
        org_id=org.org_id,
        target=str(memory_id),
    )
