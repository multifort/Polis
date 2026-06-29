"""单测（TD-017 预设语义匹配）：match_preset 语义优先 + 关键词兜底（不依赖 DB/TEI）。"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from polis.modules.org import provisioning
from polis.modules.org import repository as repo
from polis.modules.org.models import ScenarioPreset
from polis.modules.org.schemas import ProvisionIn


class _GW:
    def __init__(self, vec: list[float] | None) -> None:
        self._vec = vec

    async def embed(self, texts: list[str]) -> list[list[float] | None]:
        return [self._vec]

    async def chat(self, *a: Any, **k: Any) -> Any:  # 协议占位
        raise NotImplementedError


def _p(name: str) -> ScenarioPreset:
    return ScenarioPreset(name=name, version="v1", description=name)


def test_semantic_hit_above_tau(monkeypatch: pytest.MonkeyPatch) -> None:
    target = _p("采购分析公司")

    async def _rank(_s: Any, _v: list[float], limit: int = 5) -> list[tuple[ScenarioPreset, float]]:
        return [(target, 0.71)]  # ≥ τ(0.45)

    monkeypatch.setattr(repo, "rank_presets_by_vector", _rank)
    got = asyncio.run(
        provisioning.match_preset(object(), ProvisionIn(name="x", keyword="帮我做采购"), _GW([0.1]))
    )
    assert got is target


def test_semantic_miss_falls_back_to_keyword(monkeypatch: pytest.MonkeyPatch) -> None:
    kw_preset = _p("人力资源公司")

    async def _rank(_s: Any, _v: list[float], limit: int = 5) -> list[tuple[ScenarioPreset, float]]:
        return [(_p("无关预设"), 0.30)]  # < τ → 语义未命中

    async def _list(_s: Any) -> list[ScenarioPreset]:
        return [kw_preset]

    monkeypatch.setattr(repo, "rank_presets_by_vector", _rank)
    monkeypatch.setattr(repo, "list_presets", _list)
    # 关键词「人力资源」子串命中 kw_preset
    got = asyncio.run(
        provisioning.match_preset(object(), ProvisionIn(name="x", keyword="人力资源"), _GW([0.1]))
    )
    assert got is kw_preset


def test_no_gateway_uses_keyword(monkeypatch: pytest.MonkeyPatch) -> None:
    p = _p("采购分析公司")

    async def _list(_s: Any) -> list[ScenarioPreset]:
        return [p]

    monkeypatch.setattr(repo, "list_presets", _list)
    data = ProvisionIn(name="x", keyword="采购分析")
    got = asyncio.run(provisioning.match_preset(object(), data))
    assert got is p


def test_embed_none_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    p = _p("采购分析公司")

    async def _list(_s: Any) -> list[ScenarioPreset]:
        return [p]

    monkeypatch.setattr(repo, "list_presets", _list)
    # gateway.embed 返回 None（桩/不可达）→ 语义跳过 → 关键词兜底
    got = asyncio.run(
        provisioning.match_preset(object(), ProvisionIn(name="x", keyword="采购分析"), _GW(None))
    )
    assert got is p
