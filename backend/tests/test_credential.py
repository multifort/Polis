"""单元测试（M6-B）：信封加密往返 + KMS 缺失/损坏。无 DB。"""

from __future__ import annotations

import base64
import secrets

import pytest

from polis.config import get_settings
from polis.modules.model import credential


def _set_kms(monkeypatch: pytest.MonkeyPatch, key: str | None) -> None:
    get_settings.cache_clear()
    if key is None:
        monkeypatch.delenv("POLIS_KMS_MASTER_KEY", raising=False)
        monkeypatch.setattr(get_settings(), "kms_master_key", "", raising=False)
    else:
        monkeypatch.setattr(get_settings(), "kms_master_key", key, raising=False)


def _fresh_kms() -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()


def test_envelope_roundtrip(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_kms(monkeypatch, _fresh_kms())
    ct, dek = credential.encrypt_credential("sk-secret-123")
    # 密文不含明文
    assert b"sk-secret-123" not in ct
    assert b"sk-secret-123" not in dek
    assert credential.decrypt_credential(ct, dek) == "sk-secret-123"


def test_decrypt_fails_with_wrong_kms(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_kms(monkeypatch, _fresh_kms())
    ct, dek = credential.encrypt_credential("sk-secret")
    _set_kms(monkeypatch, _fresh_kms())  # 换主密钥
    with pytest.raises(credential.CredentialError):
        credential.decrypt_credential(ct, dek)


def test_missing_kms_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_kms(monkeypatch, "")
    with pytest.raises(credential.CredentialError, match="KMS"):
        credential.encrypt_credential("sk")
    get_settings.cache_clear()


def test_scoped_credential_value_hidden_in_repr() -> None:
    sc = credential.ScopedCredential(handle="h", model_id="m", task_id="t", value="sk-secret")
    assert "sk-secret" not in repr(sc)  # 防明文误打印
