"""async 引擎与会话工厂。引擎在应用 lifespan 中创建/销毁（TD-006），不在 import 时建。"""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from polis.config import get_settings

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def init_engine() -> None:
    """应用启动时调用：建引擎 + 会话工厂。"""
    global _engine, _sessionmaker
    if _engine is None:
        _engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
        _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)


async def dispose_engine() -> None:
    """应用关闭时调用：释放连接池。"""
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _sessionmaker = None


def get_engine() -> AsyncEngine:
    if _engine is None:
        raise RuntimeError("engine 未初始化（应在 lifespan 内 init_engine）")
    return _engine


async def get_session() -> AsyncIterator[AsyncSession]:
    """每请求一个事务：成功提交、异常回滚。

    这样 OrgContext 里的 `SET LOCAL ROLE polis_app` + 当前公司设置能贯穿整个请求，
    事务结束自动复位，连接归池前不残留（避免跨租户泄漏）。service 层只 flush，不 commit。
    """
    if _sessionmaker is None:
        raise RuntimeError("sessionmaker 未初始化（应在 lifespan 内 init_engine）")
    async with _sessionmaker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
