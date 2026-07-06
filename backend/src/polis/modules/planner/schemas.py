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
    # 预算治理（V2-B4，分层覆盖 节点>任务>全局）。出图时由 budget.apply_budgets 回填解析值。
    ctx_budget: int | None = None  # 输入上下文 token 预算（截输入）
    max_output_tokens: int | None = None  # 输出 token 上限（仅设上限，绝不截已生成内容）


class PlanDag(BaseModel):
    workflow_name: str
    goal: str
    acceptance_criteria: str | None = None
    budget_cents: int = 0
    # 任务级预算（V2-B4，可选；缺省走节点类型智能缺省/全局）。节点未显式覆盖时用它。
    ctx_budget: int | None = None
    output_max_tokens: int | None = None
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
    status: str  # "running" or "pending"


class RunNodeState(BaseModel):
    id: str
    status: str
    agent: str | None = None


class RunStatusResult(BaseModel):
    status: str
    nodes: list[RunNodeState]


class SignalIn(BaseModel):
    node_id: str


# ── 任务实体（V2-P1）──────────────────────────────────────────────────────────


class TaskCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    goal: str = Field(min_length=1)
    scenario_ref: str | None = None
    input_schema: dict[str, object] | None = None
    inputs: dict[str, object] | None = None
    priority: int | None = Field(default=None, ge=0, le=100)


class TaskOut(BaseModel):
    id: uuid.UUID
    name: str
    goal: str
    scenario_ref: str | None = None
    priority: int = 0
    status: str


class AttachmentOut(BaseModel):
    """任务附件（登记为 artifact_descriptor，文件存 MinIO）。"""

    id: uuid.UUID
    filename: str
    mime: str | None = None
    size: int
    uri: str
    field: str | None = None
    created_at: str | None = None


class AttachmentUrlOut(BaseModel):
    """预签名下载链接（短时）。"""

    url: str
    expires_seconds: int


class TaskRunOut(BaseModel):
    id: uuid.UUID
    task_id: uuid.UUID | None = None
    plan_id: uuid.UUID | None = None
    status: str
    priority: int = 0
    created_at: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    estimated_cost_cents: int | None = None
    actual_cost: float | None = None  # 真实 LLM 调用费用（元）


# ── C0-4 工作台 workspace runs ──────────────────────────────────────────────────


class WorkspaceRunItem(BaseModel):
    """工作台展示用：一次运行的摘要（关联任务信息）。"""

    run_id: uuid.UUID
    task_id: uuid.UUID | None = None
    task_name: str | None = None
    task_goal: str | None = None
    plan_id: uuid.UUID | None = None
    run_status: str
    started_at: str | None = None
    finished_at: str | None = None
    node_count: int = 0
    estimated_cost_cents: int | None = None
    actual_cost: float | None = None  # 真实 LLM 调用费用（元）


# ── P4 看板：跨任务/场景运营统计 ──────────────────────────────────────────────────


class TemplateDistItem(BaseModel):
    """按场景(模板)分布的一行：模板名/命中次数/是否为模板命中(否则=生成)。"""

    template: str
    count: int
    is_template_hit: bool


class DashboardStats(BaseModel):
    """跨 task_run 聚合的运营统计（design v2/05 §8）。"""

    total_runs: int
    by_status: dict[str, int]
    success_rate: float | None = None  # done / 全部终态（done+failed+needs_review+needs_rework）
    avg_duration_seconds: float | None = None
    active_runs: int
    org_max_concurrent_runs: int
    reuse_hit_rate: float | None = None  # 模板命中次数 / 全部运行次数（飞轮指标）
    approval_pass_rate: float | None = None  # 人审通过 / 人审已决（approved+rejected）
    by_template: list[TemplateDistItem]
    # 近期窗口（最近 N 条运行）实测成本/token 聚合，避免全量 langfuse 拉取过慢
    recent_window: int
    recent_total_cost: float | None = None
    recent_total_tokens: int | None = None
    budget_cents: int = 0  # 0=未设预算（S3 仅提示）
    estimated_cost_cents: int = 0  # 累计预估成本（分）


class WorkspaceRuns(BaseModel):
    active: list[WorkspaceRunItem] = []
    recent: list[WorkspaceRunItem] = []


# ── R3 场景模板沉淀 ──────────────────────────────────────────────────


class SaveAsTemplateIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    domain: str | None = None
    subcategory: str | None = None


class TemplateOut(BaseModel):
    id: uuid.UUID
    name: str
    version: str
    domain: str | None = None
    subcategory: str | None = None
    source: str = "builtin"
    visibility: str = "public"


# ── P5 场景分类 ─────────────────────────────────────────────────────


class SceneCategoryIn(BaseModel):
    domain: str = Field(min_length=1, max_length=100)
    subcategory: str | None = None


class SceneCategoryOut(BaseModel):
    id: uuid.UUID
    domain: str
    subcategory: str | None = None
    org_id: uuid.UUID | None = None


def derive_overall_status(node_statuses: list[str]) -> str:
    """从节点状态派生顶层运行状态：有 failed→failed；全 done→done；否则 running。

    waiting_human 视为 running（人审挂起仍在运行中）。空节点列表保守返回 running。
    """
    if not node_statuses:
        return "running"
    if any(s == "failed" for s in node_statuses):
        return "failed"
    if any(s == "needs_rework" for s in node_statuses):  # V2-S1：关键节点质量不达标
        return "needs_review"
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
