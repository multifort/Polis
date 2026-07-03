"""单测（A2 规划生成）：generate_dag RAG 接地 + 双校验 + 有界自修复（不依赖真实 LLM）。

用 StubModelGateway 脚本化 LLM 输出，验证：
1. 一次过合法 JSON → 返回 PlanDag；
2. 首轮结构非法 / 语义非法 → 反馈错误 → 次轮修正 → 通过（有界自修复）；
3. N 轮都不过 → PlanInvalid（携带最后一轮错误）。
"""

from __future__ import annotations

import asyncio
import json

import pytest

from polis.modules.model.gateway import ChatResponse, ResolvedModel, StubModelGateway
from polis.modules.planner.errors import PlanInvalid
from polis.modules.planner.generator import _build_user, generate_dag, generate_subdag
from polis.modules.planner.schemas import PlanDag, PlanNode

_MODEL = ResolvedModel(id="m", provider="p", litellm_name="n", context_window=8000)


def _valid_dag_json(cap: str = "analysis") -> str:
    return json.dumps(
        {
            "workflow_name": "wf",
            "goal": "g",
            "budget_cents": 1000,
            "nodes": [{"id": "n1", "type": "agent", "deps": [], "required_capabilities": [cap]}],
        }
    )


def _run(gw: StubModelGateway, available: set[str]) -> object:
    return asyncio.run(generate_dag(gw, _MODEL, "目标", available, exemplars=[]))


def test_valid_first_try() -> None:
    gw = StubModelGateway(script=[ChatResponse(content=_valid_dag_json())])
    dag = _run(gw, {"analysis"})
    assert dag.nodes[0].required_capabilities == ["analysis"]


def test_valid_with_markdown_fence() -> None:
    fenced = "```json\n" + _valid_dag_json() + "\n```"
    gw = StubModelGateway(script=[ChatResponse(content=fenced)])
    dag = _run(gw, {"analysis"})
    assert dag.workflow_name == "wf"


def test_self_repair_after_bad_json() -> None:
    gw = StubModelGateway(
        script=[
            ChatResponse(content="对不起，这不是 JSON"),  # 结构非法
            ChatResponse(content=_valid_dag_json()),  # 修正
        ]
    )
    dag = _run(gw, {"analysis"})
    assert len(dag.nodes) == 1


def test_self_repair_after_capability_error() -> None:
    gw = StubModelGateway(
        script=[
            ChatResponse(content=_valid_dag_json(cap="not_active")),  # 语义：能力不在 available
            ChatResponse(content=_valid_dag_json(cap="analysis")),  # 修正
        ]
    )
    dag = _run(gw, {"analysis"})
    assert dag.nodes[0].required_capabilities == ["analysis"]


def test_give_up_raises_plan_invalid() -> None:
    gw = StubModelGateway(
        script=[
            ChatResponse(content=_valid_dag_json(cap="bad")),
            ChatResponse(content=_valid_dag_json(cap="bad")),
        ]
    )
    with pytest.raises(PlanInvalid) as ei:
        _run(gw, {"analysis"})
    assert any("能力" in e for e in ei.value.errors)


def test_build_user_injects_org_memory() -> None:
    # B2：org 记忆先验注入生成 prompt（供约束/取舍）
    prompt = _build_user(
        "分析供应商",
        {"analysis"},
        exemplars=[],
        org_memory=["供应商A交付准时率仅60%", "6天交付为硬约束"],
    )
    assert "公司已知" in prompt
    assert "供应商A交付准时率仅60%" in prompt
    assert "6天交付为硬约束" in prompt


def test_build_user_no_memory_section_when_empty() -> None:
    prompt = _build_user("目标", {"analysis"}, exemplars=[], org_memory=[])
    assert "公司已知" not in prompt


def _base_replan_dag() -> PlanDag:
    return PlanDag(
        workflow_name="wf",
        goal="修复流程",
        budget_cents=2000,
        nodes=[
            PlanNode(id="n1", type="agent", deps=[], required_capabilities=["analysis"]),
            PlanNode(id="n2", type="agent", deps=["n1"], required_capabilities=["analysis"]),
            PlanNode(id="n3", type="agent", deps=["n2"], required_capabilities=["report"]),
        ],
    )


def _replacement_nodes(cap: str = "analysis") -> str:
    return json.dumps(
        [
            {"id": "n2b", "type": "agent", "deps": ["n1"], "required_capabilities": [cap]},
            {"id": "n3b", "type": "agent", "deps": ["n2b"], "required_capabilities": ["report"]},
        ]
    )


def test_generate_subdag_valid_first_try() -> None:
    gw = StubModelGateway(script=[ChatResponse(content=_replacement_nodes())])
    nodes = asyncio.run(
        generate_subdag(gw, _MODEL, _base_replan_dag(), "n2", "执行失败", {"analysis", "report"})
    )
    assert [n["id"] for n in nodes] == ["n2b", "n3b"]


def test_generate_subdag_self_repairs_after_capability_error() -> None:
    gw = StubModelGateway(
        script=[
            ChatResponse(content=_replacement_nodes(cap="missing")),
            ChatResponse(content=_replacement_nodes(cap="analysis")),
        ]
    )
    nodes = asyncio.run(
        generate_subdag(gw, _MODEL, _base_replan_dag(), "n2", "执行失败", {"analysis", "report"})
    )
    assert nodes[0]["required_capabilities"] == ["analysis"]


def test_generate_subdag_gives_up() -> None:
    gw = StubModelGateway(
        script=[
            ChatResponse(content=_replacement_nodes(cap="missing")),
            ChatResponse(content=_replacement_nodes(cap="missing")),
        ]
    )
    with pytest.raises(PlanInvalid) as ei:
        asyncio.run(
            generate_subdag(
                gw, _MODEL, _base_replan_dag(), "n2", "执行失败", {"analysis", "report"}
            )
        )
    assert any("能力" in e for e in ei.value.errors)
