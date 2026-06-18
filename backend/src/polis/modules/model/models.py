"""model 模块 ORM：模型目录(全局,无密钥) + 凭证(用户级,信封密文)。

设计：docs/design/06、0b。credential 永不存明文（密文 + KMS 包裹的 DEK）。
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import (
    BigInteger,
    ForeignKey,
    Integer,
    LargeBinary,
    Numeric,
    PrimaryKeyConstraint,
    Text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from polis.db.base import Base


class ModelCatalog(Base):
    __tablename__ = "model_catalog"

    id: Mapped[str] = mapped_column(Text, primary_key=True)  # 如 'deepseek-chat'
    provider: Mapped[str | None] = mapped_column(Text)
    litellm_name: Mapped[str | None] = mapped_column(Text)
    capabilities: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    context_window: Mapped[int | None] = mapped_column(Integer)
    price_in: Mapped[float | None] = mapped_column(Numeric)
    price_out: Mapped[float | None] = mapped_column(Numeric)
    connector: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class Credential(Base):
    """BYO-Key 信封加密存储，按 (user_id, model_id)。永不落明文。"""

    __tablename__ = "credential"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"))
    model_id: Mapped[str] = mapped_column(ForeignKey("model_catalog.id"))
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary)
    dek_wrapped: Mapped[bytes] = mapped_column(LargeBinary)
    budget_cents: Mapped[int | None] = mapped_column(BigInteger)

    __table_args__ = (PrimaryKeyConstraint("user_id", "model_id"),)
