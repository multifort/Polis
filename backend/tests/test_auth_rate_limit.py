"""登录失败限流（TD-013）的纯逻辑测试。"""

from __future__ import annotations

from polis.config import Settings
from polis.modules.org import auth_rate_limit


def test_login_rate_limit_locks_after_configured_failures() -> None:
    auth_rate_limit.reset_for_tests()
    settings = Settings(
        auth_login_max_failures=3,
        auth_login_window_seconds=60,
        auth_login_lock_seconds=30,
    )

    assert (
        auth_rate_limit.retry_after_seconds("A@EXAMPLE.COM", "1.2.3.4", now=0, settings=settings)
        is None
    )
    assert (
        auth_rate_limit.record_failure("a@example.com", "1.2.3.4", now=0, settings=settings) is None
    )
    assert (
        auth_rate_limit.record_failure("a@example.com", "1.2.3.4", now=1, settings=settings) is None
    )
    assert (
        auth_rate_limit.record_failure("a@example.com", "1.2.3.4", now=2, settings=settings) == 30
    )
    assert (
        auth_rate_limit.retry_after_seconds("a@example.com", "1.2.3.4", now=12, settings=settings)
        == 20
    )
    assert (
        auth_rate_limit.retry_after_seconds("a@example.com", "1.2.3.4", now=33, settings=settings)
        is None
    )
    assert (
        auth_rate_limit.record_failure("a@example.com", "1.2.3.4", now=34, settings=settings)
        is None
    )


def test_login_rate_limit_success_clears_bucket() -> None:
    auth_rate_limit.reset_for_tests()
    settings = Settings(
        auth_login_max_failures=2,
        auth_login_window_seconds=60,
        auth_login_lock_seconds=30,
    )

    auth_rate_limit.record_failure("a@example.com", "1.2.3.4", now=0, settings=settings)
    auth_rate_limit.record_success("a@example.com", "1.2.3.4")

    assert (
        auth_rate_limit.record_failure("a@example.com", "1.2.3.4", now=1, settings=settings) is None
    )
