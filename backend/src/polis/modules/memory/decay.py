"""记忆衰减/遗忘 CLI（design 05 §5）：每日运维调用。

python -m polis.modules.memory.decay
"""

from __future__ import annotations

import asyncio
import logging

from polis.db.session import dispose_engine, get_sessionmaker, init_engine
from polis.modules.memory import repository as repo

logger = logging.getLogger(__name__)


async def run() -> dict[str, int]:
    init_engine()
    try:
        async with get_sessionmaker()() as session:
            stats = await repo.decay_and_cleanup(session)
            await session.commit()
            logger.info("记忆衰减完成：%s", stats)
            return stats
    finally:
        await dispose_engine()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run())
