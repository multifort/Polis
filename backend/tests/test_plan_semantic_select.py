"""单测（A1 检索升级）：service._select_template 语义优先 + 确定性兜底分支。

不依赖 DB / TEI：monkeypatch repo 与一个假向量网关，验证选模板的分支逻辑：
1. 网关给出向量 → 取语义排序中第一个「能力可行」的模板（不是列表顺序第一个）；
2. 语义候选都不可行 → 落确定性「list 第一个可行」兜底；
3. 无网关 / embedding 失败 → 直接走确定性兜底。
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from polis.modules.planner import repository as repo
from polis.modules.planner import service
from polis.modules.planner.models import PlanTemplate


def _tpl(name: str, caps: list[str]) -> PlanTemplate:
    nodes = [{"id": "n1", "required_capabilities": caps}]
    return PlanTemplate(name=name, version="v1", dag_skeleton={"nodes": nodes})


class _FakeGateway:
    """embed 返回固定向量；script=None 时模拟服务不可达（抛错）。"""

    def __init__(self, vec: list[float] | None) -> None:
        self._vec = vec

    async def embed(self, texts: list[str]) -> list[list[float] | None]:
        if self._vec is None:
            raise RuntimeError("TEI down")
        return [self._vec]


def _patch(
    monkeypatch: pytest.MonkeyPatch, *, ranked: list[PlanTemplate], listed: list[PlanTemplate]
) -> None:
    async def _rank(_s: Any, _v: list[float], limit: int = 10) -> list[PlanTemplate]:
        return ranked

    async def _list(_s: Any) -> list[PlanTemplate]:
        return listed

    monkeypatch.setattr(repo, "rank_plan_templates_by_goal", _rank)
    monkeypatch.setattr(repo, "list_plan_templates", _list)


def test_semantic_picks_most_similar_feasible(monkeypatch: pytest.MonkeyPatch) -> None:
    a, b = _tpl("a", ["x"]), _tpl("b", ["x"])
    # 语义排序里 b 排在前（更相似）；二者都可行 → 选 b（而非 list 顺序的 a）
    _patch(monkeypatch, ranked=[b, a], listed=[a, b])
    chosen = asyncio.run(
        service._select_template(object(), {"x"}, "目标", _FakeGateway([0.1] * 1024))
    )
    assert chosen is b


def test_semantic_skips_infeasible_top(monkeypatch: pytest.MonkeyPatch) -> None:
    infeasible, feasible = _tpl("need_y", ["y"]), _tpl("ok", ["x"])
    # 语义最相似的不可行（缺 y），第二个可行 → 选第二个
    _patch(monkeypatch, ranked=[infeasible, feasible], listed=[feasible])
    chosen = asyncio.run(
        service._select_template(object(), {"x"}, "目标", _FakeGateway([0.1] * 1024))
    )
    assert chosen is feasible


def test_fallback_when_all_ranked_infeasible(monkeypatch: pytest.MonkeyPatch) -> None:
    ranked_infeasible = _tpl("need_y", ["y"])
    det = _tpl("det", ["x"])
    _patch(monkeypatch, ranked=[ranked_infeasible], listed=[det])
    chosen = asyncio.run(
        service._select_template(object(), {"x"}, "目标", _FakeGateway([0.1] * 1024))
    )
    assert chosen is det  # 落确定性兜底


def test_fallback_no_gateway(monkeypatch: pytest.MonkeyPatch) -> None:
    first, second = _tpl("first", ["x"]), _tpl("second", ["x"])
    _patch(monkeypatch, ranked=[second], listed=[first, second])
    chosen = asyncio.run(service._select_template(object(), {"x"}, "目标", None))
    assert chosen is first  # 无网关 → 确定性「list 第一个可行」


def test_fallback_when_embed_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    first, second = _tpl("first", ["x"]), _tpl("second", ["x"])
    _patch(monkeypatch, ranked=[second], listed=[first, second])
    # 网关 embed 抛错（TEI 不可达）→ 回退确定性
    chosen = asyncio.run(service._select_template(object(), {"x"}, "目标", _FakeGateway(None)))
    assert chosen is first


def test_none_when_no_feasible(monkeypatch: pytest.MonkeyPatch) -> None:
    only = _tpl("need_y", ["y"])
    _patch(monkeypatch, ranked=[only], listed=[only])
    chosen = asyncio.run(
        service._select_template(object(), {"x"}, "目标", _FakeGateway([0.1] * 1024))
    )
    assert chosen is None  # 无可行模板 → service.plan 会 raise NoTemplateMatch
