"""单测（A1 检索校准）：模板 embedding 源文本 _tpl_text 聚合中文意图、不掺英文标识符。"""

from __future__ import annotations

from polis.modules.model.embed_backfill import _tpl_text
from polis.modules.planner.models import PlanTemplate


def _tpl(skeleton: dict) -> PlanTemplate:
    t = PlanTemplate(name="supplier_analysis_v1", version="v1", dag_skeleton=skeleton)
    return t


def test_tpl_text_aggregates_chinese_intent_not_identifiers() -> None:
    txt = _tpl_text(
        _tpl(
            {
                "workflow_name": "supplier_analysis",
                "acceptance_criteria": "产出供应商交付分析报告",
                "nodes": [
                    {"input_hint": "向供应商询价比价", "expected_output": "询价结果"},
                    {"input_hint": "分析供应商交付表现与风险", "expected_output": "供应商分析"},
                ],
            }
        )
    )
    # 含中文意图（验收标准 + 节点 hint/产出）
    assert "产出供应商交付分析报告" in txt
    assert "分析供应商交付表现与风险" in txt
    assert "询价结果" in txt
    # 不含英文标识符噪声（对 bge-zh 拉低相似度）
    assert "supplier_analysis" not in txt
    assert "supplier_analysis_v1" not in txt


def test_tpl_text_falls_back_to_name_when_no_chinese() -> None:
    # 骨架无任何中文文本 → 退回 name（不至于空串）
    assert _tpl_text(_tpl({"nodes": []})) == "supplier_analysis_v1"
