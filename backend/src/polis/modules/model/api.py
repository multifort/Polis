"""模型凭证 API（design 06 §7）：owner 配置公司模型 Key（BYO-Key，信封加密入库）。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from polis.db.session import get_session
from polis.modules.model import credential
from polis.modules.model import repository as repo
from polis.modules.model.models import ModelCatalog
from polis.modules.observability.audit import write_audit
from polis.modules.org.deps import CurrentUserId, OrgContext, require_role

router = APIRouter(prefix="/api", tags=["model"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
# 配置公司模型凭证：仅 owner（凭证归 owner，代表公司）
OwnerOrg = Annotated[OrgContext, Depends(require_role("owner"))]


class CredentialIn(BaseModel):
    model_id: str = Field(min_length=1)
    api_key: str = Field(min_length=1)
    budget_cents: int | None = None


class CredentialOut(BaseModel):
    model_id: str
    configured: bool


@router.post("/credentials", response_model=CredentialOut, status_code=status.HTTP_201_CREATED)
async def configure_credential(
    data: CredentialIn, org: OwnerOrg, user_id: CurrentUserId, session: SessionDep
) -> CredentialOut:
    """owner 为公司配置某模型的 Key（信封加密存；明文永不入库/日志）。"""
    model = await session.get(ModelCatalog, data.model_id)
    if model is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "模型不在目录中")
    try:
        ciphertext, dek_wrapped = credential.encrypt_credential(data.api_key)
    except credential.CredentialError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "凭证加密未就绪") from exc

    await repo.upsert_credential(
        session, user_id, data.model_id, ciphertext, dek_wrapped, data.budget_cents
    )
    await write_audit(
        session,
        action="credential.configure",
        actor=str(user_id),
        org_id=org.org_id,
        target=data.model_id,
    )
    return CredentialOut(model_id=data.model_id, configured=True)
