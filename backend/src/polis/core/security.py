"""口令哈希(argon2) 与 JWT(access/refresh)。access 不携带 org/权限（09 §3）。"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from polis.config import get_settings

_ph = PasswordHasher()


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _ph.verify(password_hash, password)
    except VerifyMismatchError:
        return False


def hash_token(token: str) -> str:
    """refresh token 存哈希，不存明文。"""
    return hashlib.sha256(token.encode()).hexdigest()


def _encode(sub: uuid.UUID, token_type: str, ttl: timedelta) -> tuple[str, datetime]:
    s = get_settings()
    expires_at = datetime.now(UTC) + ttl
    payload: dict[str, Any] = {
        "sub": str(sub),
        "type": token_type,
        "exp": expires_at,
        "iat": datetime.now(UTC),
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, s.jwt_secret, algorithm=s.jwt_alg), expires_at


def create_access_token(user_id: uuid.UUID) -> str:
    s = get_settings()
    token, _ = _encode(user_id, "access", timedelta(minutes=s.access_ttl_min))
    return token


def create_refresh_token(user_id: uuid.UUID) -> tuple[str, datetime]:
    s = get_settings()
    return _encode(user_id, "refresh", timedelta(days=s.refresh_ttl_days))


def decode_token(token: str) -> dict[str, Any]:
    s = get_settings()
    return jwt.decode(token, s.jwt_secret, algorithms=[s.jwt_alg])
