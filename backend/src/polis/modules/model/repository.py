"""model 数据访问层：凭证(信封密文) + org owner 查询。集中 SQL（12 C 分层）。"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from polis.modules.model.models import Credential, ModelCatalog
from polis.modules.org.models import Org


async def models_by_capability(session: AsyncSession, capability: str) -> list[ModelCatalog]:
    """目录中具备某能力的模型（成本路由候选）。"""
    rows = await session.scalars(
        select(ModelCatalog).where(ModelCatalog.capabilities.contains([capability]))
    )
    return list(rows.all())


async def get_org_owner(session: AsyncSession, org_id: uuid.UUID) -> uuid.UUID | None:
    """取 org 所有者 user_id（公司模型凭证归 owner，design 06 §2.2）。"""
    owner: uuid.UUID | None = await session.scalar(
        select(Org.owner_user_id).where(Org.id == org_id)
    )
    return owner


async def get_credential(
    session: AsyncSession, user_id: uuid.UUID, model_id: str
) -> Credential | None:
    cred: Credential | None = await session.get(
        Credential, {"user_id": user_id, "model_id": model_id}
    )
    return cred


async def upsert_credential(
    session: AsyncSession,
    user_id: uuid.UUID,
    model_id: str,
    ciphertext: bytes,
    dek_wrapped: bytes,
    budget_cents: int | None = None,
) -> Credential:
    cred = await get_credential(session, user_id, model_id)
    if cred is None:
        cred = Credential(
            user_id=user_id,
            model_id=model_id,
            ciphertext=ciphertext,
            dek_wrapped=dek_wrapped,
            budget_cents=budget_cents,
        )
        session.add(cred)
    else:
        cred.ciphertext = ciphertext
        cred.dek_wrapped = dek_wrapped
        cred.budget_cents = budget_cents
    await session.flush()
    return cred
