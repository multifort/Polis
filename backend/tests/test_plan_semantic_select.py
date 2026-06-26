"""单测（A1 检索）：service._retrieve_template 语义择优 + 确定性兜底（不依赖 DB/TEI）。"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from polis.modules.planner import repository as repo
from polis.modules.planner import service
from polis.modules.planner.models import PlanTemplate


def _tpl(name: str, caps: list[str], emb: list[float] | None = None) -> PlanTemplate:
    nodes = [{"id": "n1", "required_capabilities": caps}]
    t = PlanTemplate(name=name, version="v1", dag_skeleton={"nodes": nodes})
    t.embedding = emb
    return t


def _patch(
    monkeypatch: pytest.MonkeyPatch, *, ranked: list[PlanTemplate], listed: list[PlanTemplate]
) -> None:
    async def _rank(_s: Any, _v: list[float], limit: int = 10) -> list[PlanTemplate]:
        return ranked

    async def _list(_s: Any) -> list[PlanTemplate]:
        return listed

    monkeypatch.setattr(repo, "rank_plan_templates_by_goal", _rank)
    monkeypatch.setattr(repo, "list_plan_templates", _list)


def test_semantic_picks_first_feasible_in_rank(monkeypatch: pytest.MonkeyPatch) -> None:
    a, b = _tpl("a", ["x"], [1.0, 0.0]), _tpl("b", ["x"], [0.0, 1.0])
    # 语义排序里 b 在前 → 选 b（而非 list 顺序的 a）；sim=cosine(query, b.embedding)
    _patch(monkeypatch, ranked=[b, a], listed=[a, b])
    chosen, sim = asyncio.run(service._retrieve_template(object(), {"x"}, [0.0, 1.0]))
    assert chosen is b
    assert sim == pytest.approx(1.0)


def test_numpy_embedding_does_not_crash(monkeypatch: pytest.MonkeyPatch) -> None:
    # 回归：pgvector 取回是 numpy 数组，`if emb` 会抛 ambiguous truth value（须 is not None）
    import numpy as np

    t = _tpl("a", ["x"])
    t.embedding = np.array([0.0, 1.0])
    _patch(monkeypatch, ranked=[t], listed=[t])
    chosen, sim = asyncio.run(service._retrieve_template(object(), {"x"}, [0.0, 1.0]))
    assert chosen is t
    assert sim == pytest.approx(1.0)


def test_semantic_skips_infeasible_top(monkeypatch: pytest.MonkeyPatch) -> None:
    infeasible = _tpl("need_y", ["y"], [1.0, 0.0])
    feasible = _tpl("ok", ["x"], [0.0, 1.0])
    _patch(monkeypatch, ranked=[infeasible, feasible], listed=[feasible])
    chosen, _ = asyncio.run(service._retrieve_template(object(), {"x"}, [0.0, 1.0]))
    assert chosen is feasible


def test_fallback_no_vec_first_feasible(monkeypatch: pytest.MonkeyPatch) -> None:
    first, second = _tpl("first", ["x"]), _tpl("second", ["x"])
    _patch(monkeypatch, ranked=[second], listed=[first, second])
    chosen, sim = asyncio.run(service._retrieve_template(object(), {"x"}, None))
    assert chosen is first  # 无向量 → 确定性「list 第一个可行」
    assert sim == 1.0


def test_none_when_no_feasible(monkeypatch: pytest.MonkeyPatch) -> None:
    only = _tpl("need_y", ["y"], [1.0, 0.0])
    _patch(monkeypatch, ranked=[only], listed=[only])
    chosen, sim = asyncio.run(service._retrieve_template(object(), {"x"}, [1.0, 0.0]))
    assert chosen is None and sim == 0.0
