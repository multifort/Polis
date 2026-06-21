"""集成测试（M6-C / T6.2）：cost_aware_pick 在候选中选最便宜。"""

from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from polis.config import get_settings
from polis.modules.model.litellm_gateway import cost_aware_pick
from polis.seed import seed


def test_cost_aware_pick_chooses_cheapest_text_gen(client: TestClient) -> None:
    asyncio.run(seed())

    async def _run() -> None:
        engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as s:
                pick = await cost_aware_pick(s, "text-gen")
                # text-gen 候选：deepseek-v4-pro / deepseek-v4-flash / claude-opus → flash 最便宜
                assert pick is not None
                assert pick.id == "deepseek-v4-flash"

                # 无此能力 → None
                assert await cost_aware_pick(s, "no-such-capability") is None
        finally:
            await engine.dispose()

    asyncio.run(_run())
