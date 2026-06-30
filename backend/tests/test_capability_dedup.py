"""单测（TD-030 / §14.4 能力语义去重）：resolve_capability 复用近义 key / 新能力返 None。"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from polis.modules.planner import repository as planner_repo
from polis.modules.planner import skillgen
from polis.modules.planner.models import Capability


class _GW:
    def __init__(self, vec: list[float] | None) -> None:
        self._vec = vec

    async def embed(self, texts: list[str]) -> list[list[float] | None]:
        return [self._vec]

    async def chat(self, *a: Any, **k: Any) -> Any:
        raise NotImplementedError


def _cap(key: str) -> Capability:
    return Capability(key=key, name=key)


def test_dedup_reuses_near_synonym(monkeypatch: pytest.MonkeyPatch) -> None:
    existing = _cap("report.generation")

    async def _rank(_s: Any, _v: list[float], limit: int = 5) -> list[tuple[Capability, float]]:
        return [(existing, 0.91)]  # ≥ τ_dedup(0.86) → 复用

    monkeypatch.setattr(planner_repo, "rank_capabilities_by_vector", _rank)
    got = asyncio.run(skillgen.resolve_capability(object(), _GW([0.1]), "report.make", "出报告"))
    assert got == "report.generation"


def test_new_capability_below_tau(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _rank(_s: Any, _v: list[float], limit: int = 5) -> list[tuple[Capability, float]]:
        return [(_cap("procurement.rfq"), 0.40)]  # < τ → 确为新能力

    monkeypatch.setattr(planner_repo, "rank_capabilities_by_vector", _rank)
    got = asyncio.run(skillgen.resolve_capability(object(), _GW([0.1]), "market.sentiment", "舆情"))
    assert got is None


def test_embed_none_returns_none() -> None:
    got = asyncio.run(skillgen.resolve_capability(object(), _GW(None), "x", "y"))
    assert got is None
