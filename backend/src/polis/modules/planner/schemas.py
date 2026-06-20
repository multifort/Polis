"""Plan(DAG) schema 与校验（design 03 §3/§4）。模板与 LLM 产出同构；M3 走模板优先。"""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, Field

NodeType = Literal["agent", "skill", "human", "workflow", "system"]


class PlanNode(BaseModel):
    id: str
    type: NodeType = "agent"
    deps: list[str] = Field(default_factory=list)
    required_capabilities: list[str] = Field(default_factory=list)
    executor: str = "lite-agent"
    input_hint: str | None = None
    expected_output: str | None = None
    dangerous: bool = False


class PlanDag(BaseModel):
    workflow_name: str
    goal: str
    acceptance_criteria: str | None = None
    budget_cents: int = 0
    nodes: list[PlanNode]


class ValidationResult(BaseModel):
    ok: bool
    errors: list[str] = Field(default_factory=list)


class PlanCreateIn(BaseModel):
    goal: str


class PlanResult(BaseModel):
    id: uuid.UUID
    goal: str
    status: str
    template: str
    estimated_cost_cents: int
    dag: PlanDag
    routing: dict[str, str | None]  # node_id → 选中 Agent 名或 None


# 节点成本粗估（分）：确定性占位，M6 接 LiteLLM 后用真实价目
_COST_PER_NODE = {"agent": 200, "skill": 50, "human": 0, "workflow": 100, "system": 10}


def estimate_cost_cents(dag: PlanDag) -> int:
    return sum(_COST_PER_NODE.get(n.type, 100) for n in dag.nodes)


def validate(dag: PlanDag, available_capabilities: set[str]) -> ValidationResult:
    """拦截垃圾计划：无环 / 可达完整 / 能力可满足 / 预算内 / 危险动作已 gate（03 §4）。"""
    errors: list[str] = []
    ids = [n.id for n in dag.nodes]
    id_set = set(ids)

    if not dag.nodes:
        errors.append("DAG 为空")
    if len(ids) != len(id_set):
        errors.append("存在重复节点 id")

    # 依赖引用必须存在
    for n in dag.nodes:
        for d in n.deps:
            if d not in id_set:
                errors.append(f"节点 {n.id} 依赖了不存在的节点 {d}")

    # 无环（基于已存在的依赖做拓扑）
    if not _is_acyclic(dag, id_set):
        errors.append("DAG 存在环")

    # 能力可被满足
    for n in dag.nodes:
        missing = [c for c in n.required_capabilities if c not in available_capabilities]
        if missing:
            errors.append(f"节点 {n.id} 的能力无法满足：{', '.join(missing)}")

    # 危险动作必须人审 gate
    for n in dag.nodes:
        if n.dangerous and n.type != "human":
            errors.append(f"危险节点 {n.id} 必须为 human 类型（人审 gate）")

    # 预算
    if dag.budget_cents > 0 and estimate_cost_cents(dag) > dag.budget_cents:
        errors.append(f"预估成本 {estimate_cost_cents(dag)} 分 超出预算 {dag.budget_cents} 分")

    return ValidationResult(ok=not errors, errors=errors)


# ── 运行/审批 API 响应 ──────────────────────────────────────────────────────────


class ApproveResult(BaseModel):
    task_id: uuid.UUID
    status: str  # "running"


class RunNodeState(BaseModel):
    id: str
    status: str
    agent: str | None = None


class RunStatusResult(BaseModel):
    status: str
    nodes: list[RunNodeState]


class SignalIn(BaseModel):
    node_id: str


def derive_overall_status(node_statuses: list[str]) -> str:
    """从节点状态派生顶层运行状态：有 failed→failed；全 done→done；否则 running。

    waiting_human 视为 running（人审挂起仍在运行中）。空节点列表保守返回 running。
    """
    if not node_statuses:
        return "running"
    if any(s == "failed" for s in node_statuses):
        return "failed"
    if all(s == "done" for s in node_statuses):
        return "done"
    return "running"


def _is_acyclic(dag: PlanDag, id_set: set[str]) -> bool:
    # Kahn 拓扑排序：能排完即无环（只看存在的依赖边）
    indeg = {n.id: 0 for n in dag.nodes}
    adj: dict[str, list[str]] = {n.id: [] for n in dag.nodes}
    for n in dag.nodes:
        for d in n.deps:
            if d in id_set:
                indeg[n.id] += 1
                adj[d].append(n.id)
    queue = [i for i, deg in indeg.items() if deg == 0]
    seen = 0
    while queue:
        cur = queue.pop()
        seen += 1
        for nxt in adj[cur]:
            indeg[nxt] -= 1
            if indeg[nxt] == 0:
                queue.append(nxt)
    return seen == len(dag.nodes)
