"""Credential Broker（design 06 §2）：信封加密 + 任务级短时句柄 + 用完即焚 + 审计。

信封加密：随机 DEK 加密用户 Key（ciphertext）；KMS 主密钥加密 DEK（dek_wrapped）。
密钥永不落明文/日志/上下文/记忆（CLAUDE §4）。M4 桩已退役，改为真实实现（M6-B）。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import AsyncSession

from polis.config import get_settings
from polis.modules.model import repository as repo
from polis.modules.observability.audit import write_audit


class CredentialError(Exception):
    """KMS 主密钥缺失/格式错，或解密失败。"""


@dataclass
class ScopedCredential:
    """任务级短时凭证句柄。value 为明文 Key（运行时用，永不日志/落盘/入库）。"""

    handle: str
    model_id: str
    task_id: str
    value: str | None = field(default=None, repr=False)  # repr=False：避免误打印明文


def _kms() -> Fernet:
    key = get_settings().kms_master_key
    if not key:
        raise CredentialError("POLIS_KMS_MASTER_KEY 未配置，无法信封加解密")
    try:
        return Fernet(key.encode())
    except Exception as exc:  # noqa: BLE001 - 主密钥格式非法
        raise CredentialError("POLIS_KMS_MASTER_KEY 格式非法（需 base64 32B）") from exc


def encrypt_credential(plaintext_key: str) -> tuple[bytes, bytes]:
    """信封加密用户 Key → (ciphertext, dek_wrapped)。"""
    dek = Fernet.generate_key()
    ciphertext = Fernet(dek).encrypt(plaintext_key.encode())
    dek_wrapped = _kms().encrypt(dek)
    return ciphertext, dek_wrapped


def decrypt_credential(ciphertext: bytes, dek_wrapped: bytes) -> str:
    """信封解密 → 明文用户 Key。"""
    try:
        dek = _kms().decrypt(dek_wrapped)
        return Fernet(dek).decrypt(ciphertext).decode()
    except CredentialError:
        raise
    except Exception as exc:  # noqa: BLE001 - 密文损坏/主密钥不匹配
        raise CredentialError("凭证解密失败") from exc


async def scoped(
    session: AsyncSession,
    org_id: uuid.UUID,
    model_id: str,
    task_id: str,
) -> ScopedCredential:
    """签发任务级短时凭证：取 org owner 对该模型的 Key（信封解密）。

    无 credential 时返回 value=None 的句柄（由 ModelGateway 用系统级 env Key 兜底，开发期）。
    """
    owner_id = await repo.get_org_owner(session, org_id)
    row = await repo.get_credential(session, owner_id, model_id) if owner_id is not None else None
    if row is None:
        return ScopedCredential(handle=f"cred:{task_id}", model_id=model_id, task_id=task_id)

    value = decrypt_credential(row.ciphertext, row.dek_wrapped)
    await write_audit(
        session, action="credential.issue", actor=str(owner_id), org_id=org_id, target=model_id
    )
    return ScopedCredential(
        handle=f"cred:{task_id}", model_id=model_id, task_id=task_id, value=value
    )
