"""登录失败限流（TD-013）：进程内滑动窗口，防基础暴力破解。

MVP 先做单进程内存限流；多实例/生产网关场景后续可替换为 Redis 或边缘限流。
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from math import ceil

from polis.config import Settings, get_settings


@dataclass
class _Bucket:
    failures: deque[float] = field(default_factory=deque)
    locked_until: float = 0.0


_buckets: dict[str, _Bucket] = {}


def _enabled(settings: Settings) -> bool:
    return (
        settings.auth_login_max_failures > 0
        and settings.auth_login_window_seconds > 0
        and settings.auth_login_lock_seconds > 0
    )


def _key(email: str, ip: str | None) -> str:
    return f"{email.strip().lower()}|{ip or '-'}"


def _prune(bucket: _Bucket, now: float, window_seconds: int) -> None:
    cutoff = now - window_seconds
    while bucket.failures and bucket.failures[0] < cutoff:
        bucket.failures.popleft()


def retry_after_seconds(
    email: str,
    ip: str | None,
    *,
    now: float | None = None,
    settings: Settings | None = None,
) -> int | None:
    settings = settings or get_settings()
    if not _enabled(settings):
        return None
    now = time.monotonic() if now is None else now
    bucket = _buckets.get(_key(email, ip))
    if bucket is None:
        return None
    if bucket.locked_until > now:
        return max(1, ceil(bucket.locked_until - now))
    if bucket.locked_until:
        _buckets.pop(_key(email, ip), None)
        return None
    if bucket.locked_until <= now:
        _prune(bucket, now, settings.auth_login_window_seconds)
        if not bucket.failures:
            _buckets.pop(_key(email, ip), None)
        return None
    return None


def record_failure(
    email: str,
    ip: str | None,
    *,
    now: float | None = None,
    settings: Settings | None = None,
) -> int | None:
    settings = settings or get_settings()
    if not _enabled(settings):
        return None
    now = time.monotonic() if now is None else now
    key = _key(email, ip)
    bucket = _buckets.setdefault(key, _Bucket())
    if bucket.locked_until > now:
        return max(1, ceil(bucket.locked_until - now))
    if bucket.locked_until:
        bucket.failures.clear()
        bucket.locked_until = 0.0
    _prune(bucket, now, settings.auth_login_window_seconds)
    bucket.failures.append(now)
    if len(bucket.failures) >= settings.auth_login_max_failures:
        bucket.locked_until = now + settings.auth_login_lock_seconds
        return settings.auth_login_lock_seconds
    return None


def record_success(email: str, ip: str | None) -> None:
    _buckets.pop(_key(email, ip), None)


def reset_for_tests() -> None:
    _buckets.clear()
