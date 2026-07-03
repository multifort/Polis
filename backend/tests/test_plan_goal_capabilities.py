"""单测（TD-032）：goal 端新能力提案接 Skill 生成链。"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from polis.modules.model.gateway import ChatResponse, ResolvedModel, StubModelGateway
from polis.modules.planner import service, skillgen

_MODEL = ResolvedModel(id="m", provider="p", litellm_name="n", context_window=8000)


def test_parse_capability_proposals_json_objects() -> None:
    raw = (
        '[{"key":"Market Sentiment","description":"分析舆情"},'
        '{"key":"report.generation","description":"生成报告"}]'
    )

    got = service._parse_capability_proposals(raw)

    assert got == [("market.sentiment", "分析舆情"), ("report.generation", "生成报告")]


def test_parse_capability_proposals_ignores_noise_and_limits() -> None:
    raw = '前缀 [{"key":"A"}, {"key":"A"}, {"key":"B"}, {"key":"C"}] 后缀'

    got = service._parse_capability_proposals(raw)

    assert got == [("a", "A"), ("b", "B")]


def test_expand_goal_capabilities_adds_auto_published(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _resolve_model(_session: Any, _model_id: str) -> ResolvedModel:
        return _MODEL

    async def _resolve_capability(
        _session: Any, _gateway: Any, name: str, description: str = ""
    ) -> str | None:
        assert name == "market.sentiment"
        assert description == "分析市场舆情"
        return None

    async def _generate_skill_draft(_session: Any, _org_id: Any, cap: str, _gateway: Any) -> Any:
        assert cap == "market.sentiment"
        return SimpleNamespace(status="published")

    monkeypatch.setattr(service, "resolve_model", _resolve_model)
    monkeypatch.setattr(skillgen, "resolve_capability", _resolve_capability)
    monkeypatch.setattr(skillgen, "generate_skill_draft", _generate_skill_draft)
    gw = StubModelGateway(
        script=[ChatResponse(content='[{"key":"market.sentiment","description":"分析市场舆情"}]')]
    )

    got = asyncio.run(
        service._expand_available_with_goal_capabilities(
            object(), object(), "分析新品口碑", {"report.generation"}, gw
        )
    )

    assert got == {"report.generation", "market.sentiment"}


def test_expand_goal_capabilities_keeps_pending_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _resolve_model(_session: Any, _model_id: str) -> ResolvedModel:
        return _MODEL

    async def _resolve_capability(
        _session: Any, _gateway: Any, name: str, description: str = ""
    ) -> str | None:
        return "existing.capability" if name == "near.duplicate" else None

    async def _generate_skill_draft(_session: Any, _org_id: Any, cap: str, _gateway: Any) -> Any:
        assert cap == "existing.capability"
        return SimpleNamespace(status="draft")

    monkeypatch.setattr(service, "resolve_model", _resolve_model)
    monkeypatch.setattr(skillgen, "resolve_capability", _resolve_capability)
    monkeypatch.setattr(skillgen, "generate_skill_draft", _generate_skill_draft)
    gw = StubModelGateway(
        script=[ChatResponse(content='[{"key":"near.duplicate","description":"近义能力"}]')]
    )

    got = asyncio.run(
        service._expand_available_with_goal_capabilities(object(), object(), "目标", set(), gw)
    )

    assert got == set()
