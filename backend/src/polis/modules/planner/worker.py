"""Temporal Worker：注册 TaskWorkflow + run_node，接 polis-tasks 队列。"""

from __future__ import annotations

import asyncio
import logging

from temporalio.client import Client
from temporalio.worker import Worker

from polis.config import get_settings
from polis.modules.planner.workflow import TASK_QUEUE, TaskWorkflow, run_node

logger = logging.getLogger(__name__)


async def main() -> None:
    settings = get_settings()
    client = await Client.connect(settings.temporal_addr)
    async with Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=[TaskWorkflow],
        activities=[run_node],
    ):
        logger.info("Polis worker 已连接 %s，监听队列 %s", settings.temporal_addr, TASK_QUEUE)
        await asyncio.Future()  # 阻塞直到被中断


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
