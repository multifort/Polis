"""登录失败限流（TD-013）：滑动窗口，防基础暴力破解。

API 路径使用数据库共享桶，保证多后端实例之间计数一致；下方内存实现保留给纯逻辑测试
和极小本地 fallback。
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from math import ceil

from sqlalchemy.ext.asyncio import AsyncSession

from polis.config import Settings, get_settings
from polis.modules.org import repository as repo


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


def _epoch(dt: datetime) -> float:
    return dt.timestamp()


def _retry_after_from_locked_until(locked_until: datetime | None, now: datetime) -> int | None:
    if locked_until is None or locked_until <= now:
        return None
    return max(1, ceil((locked_until - now).total_seconds()))


def _prune_failures(failures: list[float], now: datetime, window_seconds: int) -> list[float]:
    cutoff = _epoch(now - timedelta(seconds=window_seconds))
    return [ts for ts in failures if ts >= cutoff]


async def retry_after_seconds_db(
    session: AsyncSession,
    email: str,
    ip: str | None,
    *,
    now: datetime | None = None,
    settings: Settings | None = None,
) -> int | None:
    settings = settings or get_settings()
    if not _enabled(settings):
        return None
    now = datetime.now(UTC) if now is None else now
    key = _key(email, ip)
    row = await repo.get_rate_limit_bucket_for_update(session, key)
    if row is None:
        return None
    retry_after = _retry_after_from_locked_until(row.locked_until, now)
    if retry_after is not None:
        return retry_after
    failures = _prune_failures(list(row.failures or []), now, settings.auth_login_window_seconds)
    if not failures:
        await repo.delete_rate_limit_bucket(session, key)
        return None
    row.failures = failures
    row.locked_until = None
    row.updated_at = now
    await session.flush()
    return None


async def record_failure_db(
    session: AsyncSession,
    email: str,
    ip: str | None,
    *,
    now: datetime | None = None,
    settings: Settings | None = None,
) -> int | None:
    settings = settings or get_settings()
    if not _enabled(settings):
        return None
    now = datetime.now(UTC) if now is None else now
    row = await repo.get_or_create_rate_limit_bucket_for_update(session, _key(email, ip))
    retry_after = _retry_after_from_locked_until(row.locked_until, now)
    if retry_after is not None:
        return retry_after
    failures = _prune_failures(list(row.failures or []), now, settings.auth_login_window_seconds)
    failures.append(_epoch(now))
    row.failures = failures
    row.updated_at = now
    if len(failures) >= settings.auth_login_max_failures:
        row.locked_until = now + timedelta(seconds=settings.auth_login_lock_seconds)
        await session.flush()
        return settings.auth_login_lock_seconds
    row.locked_until = None
    await session.flush()
    return None


async def record_success_db(session: AsyncSession, email: str, ip: str | None) -> None:
    await repo.delete_rate_limit_bucket(session, _key(email, ip))


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
