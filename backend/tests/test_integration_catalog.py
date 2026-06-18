"""集成测试（批次2）：seed 幂等 + 目录读取 API。"""

from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

from polis.seed import seed


def test_seed_idempotent_and_catalog(client: TestClient) -> None:
    # 跑两次，断言计数一致（幂等）
    first = asyncio.run(seed())
    second = asyncio.run(seed())
    assert first == second == {"capabilities": 8, "models": 3, "presets": 1}

    caps = client.get("/api/catalog/capabilities").json()
    assert len(caps) == 8
    assert any(c["key"] == "procurement.supplier_analysis" for c in caps)

    models = client.get("/api/catalog/models").json()
    assert {m["id"] for m in models} == {"deepseek-chat", "claude-opus", "text-embedding-bge"}

    presets = client.get("/api/catalog/presets").json()
    assert len(presets) == 1
    assert presets[0]["name"] == "采购分析公司"
    assert len(presets[0]["required_capabilities"]) == 4
