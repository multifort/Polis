"""会话清理 CLI（TD-012）：删除已过期/已吊销的 auth_session，防止表膨胀。

运维定时调用（cron / Temporal schedule 后续）：
    python -m polis.modules.org.cleanup
"""

from __future__ import annotations

import asyncio
import logging

from polis.db.session import dispose_engine, get_sessionmaker, init_engine
from polis.modules.org import repository as repo

logger = logging.getLogger(__name__)


async def run() -> int:
    init_engine()
    try:
        async with get_sessionmaker()() as session:
            deleted = await repo.cleanup_auth_sessions(session)
            await session.commit()
            logger.info("auth_session 清理完成，删除 %d 行", deleted)
            return deleted
    finally:
        await dispose_engine()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run())
