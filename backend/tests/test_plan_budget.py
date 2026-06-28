"""单测（V2-B4 预算治理）：分层可配置 + 按节点类型智能缺省（节点>任务>类型缺省>全局）。"""

from __future__ import annotations

from polis.config import get_settings
from polis.modules.planner.budget import apply_budgets, resolve_ctx_budget, resolve_output_max
from polis.modules.planner.schemas import PlanDag, PlanNode


def _dag(nodes: list[PlanNode], **kw: object) -> PlanDag:
    return PlanDag(workflow_name="wf", goal="g", nodes=nodes, **kw)  # type: ignore[arg-type]


def test_type_default_longform_gets_bigger() -> None:
    # 报告/生成类节点 → 长文本智能缺省（明显大于普通节点），不会被一刀切掐掉
    report = PlanNode(id="r", required_capabilities=["report.generation"])
    extract = PlanNode(id="e", required_capabilities=["procurement.rfq"])
    dag = _dag([report, extract])
    assert resolve_output_max(report, dag) == 6000
    assert resolve_ctx_budget(report, dag) == 8000
    # 普通节点走全局缺省
    assert resolve_output_max(extract, dag) == get_settings().default_output_max_tokens
    assert resolve_ctx_budget(extract, dag) == get_settings().default_ctx_budget_tokens


def test_task_level_overrides_type_default() -> None:
    # 任务级预算覆盖类型缺省（但低于节点级）
    node = PlanNode(id="n", required_capabilities=["analysis"])
    dag = _dag([node], ctx_budget=1234, output_max_tokens=777)
    assert resolve_ctx_budget(node, dag) == 1234
    assert resolve_output_max(node, dag) == 777


def test_node_level_overrides_all() -> None:
    # 节点显式预算优先级最高
    node = PlanNode(
        id="n", required_capabilities=["report.generation"], ctx_budget=999, max_output_tokens=42
    )
    dag = _dag([node], ctx_budget=1234, output_max_tokens=777)
    assert resolve_ctx_budget(node, dag) == 999
    assert resolve_output_max(node, dag) == 42


def test_apply_budgets_bakes_resolved_into_nodes() -> None:
    report = PlanNode(id="r", required_capabilities=["report.generation"])
    extract = PlanNode(id="e", required_capabilities=["procurement.rfq"])
    apply_budgets(_dag([report, extract]))
    # 出图后每个节点都带上解析后的预算，执行期直接读
    assert report.max_output_tokens == 6000 and report.ctx_budget == 8000
    assert extract.ctx_budget == get_settings().default_ctx_budget_tokens
    assert extract.max_output_tokens == get_settings().default_output_max_tokens
