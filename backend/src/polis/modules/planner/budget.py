"""预算治理（V2-B4）：分层可配置 + 按节点类型智能缺省（design 02 §8，用户决策）。

要点（澄清自设计）：
- 约束的是**输入上下文** token（塞进 prompt 的 goal/依赖摘要/记忆），**绝不截输出**。
- 输出另有独立上限 `max_output_tokens`（设上限、不截已生成内容），长文本节点（报告/综合）自动给大。
- 三层覆盖：**节点显式 > 任务级 > 按节点类型智能缺省（含全局兜底）**——默认就合理、不用手配，
  需要时可在 PlanNode / PlanDag 上显式覆盖。

`apply_budgets(dag)` 在出图时把解析结果**回填进每个节点**，执行期（agent_runtime）直接读节点上的值，
无需再拿到任务级上下文。
"""

from __future__ import annotations

from polis.config import get_settings
from polis.modules.planner.schemas import PlanDag, PlanNode

# 长文本/综合类能力关键词 → 需要更大输入上下文 + 更高输出上限
_LONGFORM_KEYS = ("report", "generation", "synthesis", "summary", "write", "draft", "compose")
# 长文本节点的智能缺省（明显高于普通节点，避免一刀切掐掉长输出）
_LONGFORM_CTX = 8000
_LONGFORM_OUTPUT = 6000


def _is_longform(node: PlanNode) -> bool:
    return any(k in cap for cap in node.required_capabilities for k in _LONGFORM_KEYS)


def resolve_ctx_budget(node: PlanNode, dag: PlanDag) -> int:
    """输入上下文预算：节点显式 > 任务级 > 节点类型智能缺省（长文本大）> 全局缺省。"""
    if node.ctx_budget is not None:
        return node.ctx_budget
    if dag.ctx_budget is not None:
        return dag.ctx_budget
    if _is_longform(node):
        return _LONGFORM_CTX
    return get_settings().default_ctx_budget_tokens


def resolve_output_max(node: PlanNode, dag: PlanDag) -> int:
    """输出 token 上限：节点显式 > 任务级 > 节点类型智能缺省（长文本大）> 全局缺省。"""
    if node.max_output_tokens is not None:
        return node.max_output_tokens
    if dag.output_max_tokens is not None:
        return dag.output_max_tokens
    if _is_longform(node):
        return _LONGFORM_OUTPUT
    return get_settings().default_output_max_tokens


def apply_budgets(dag: PlanDag) -> PlanDag:
    """出图时回填每个节点的解析预算（节点>任务>智能缺省），执行期直接读。原地改并返回。"""
    for node in dag.nodes:
        node.ctx_budget = resolve_ctx_budget(node, dag)
        node.max_output_tokens = resolve_output_max(node, dag)
    return dag
