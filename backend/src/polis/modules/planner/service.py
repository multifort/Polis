"""planner 业务逻辑：检索 → 生成 → 校验 → 路由（design v2/01 §4）。

退化链（ADR-0006 演进）：① 语义检索可复用模板（命中即填，省且稳）→ ② 未命中则 RAG 接地
LLM 生成 DAG（A2，偿还 TD-020）→ ③ 确定性双校验 → ④ 确定性路由。不依赖 web，错误以领域
异常抛出，由 api 层翻译为 HTTP。
"""

from __future__ import annotations

import copy
import logging
import math
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from polis.config import get_settings
from polis.modules.model.gateway import ModelGateway, resolve_model
from polis.modules.planner import repository as repo
from polis.modules.planner.composer import route_or_compose
from polis.modules.planner.errors import NoTemplateMatch, PlanInvalid
from polis.modules.planner.models import PlanTemplate
from polis.modules.planner.schemas import PlanDag, PlanResult, estimate_cost_cents, validate

logger = logging.getLogger(__name__)

__all__ = ["NoTemplateMatch", "PlanInvalid", "plan"]

# 模板命中相似度阈值：top-1 可行模板的 goal↔模板余弦 < τ → 判「未命中」转生成（design §14 阈值表）
TAU_TPL = 0.78
_EXEMPLAR_K = 3  # RAG 接地范例数


def _feasible(tpl: PlanTemplate, available: set[str]) -> bool:
    """模板所有节点的能力需求是否 ⊆ 当前公司可用能力集。"""
    nodes = tpl.dag_skeleton.get("nodes", [])
    needs = {c for n in nodes for c in n.get("required_capabilities", [])}
    return needs <= available


def _cosine(a: list[float], b: list[float]) -> float:
    """余弦相似度（两个等长向量）。零向量 → 0。"""
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


async def _embed_goal(goal: str, gateway: ModelGateway | None) -> list[float] | None:
    """把 goal 向量化（检索/生成接地用）。无网关/桩/服务不可达 → None（调用方回退确定性）。"""
    if gateway is None:
        return None
    try:
        return (await gateway.embed([goal]))[0]
    except Exception:  # 检索是增强项，embedding 失败不应让出图崩；记日志后回退
        logger.warning("goal embedding 失败，回退确定性模板选择", exc_info=True)
        return None


async def _retrieve_template(
    session: AsyncSession, available: set[str], query_vec: list[float] | None
) -> tuple[PlanTemplate | None, float]:
    """检索最佳「能力可行」模板，返回 (模板, 相似度)。

    - 有 query_vec：按 goal 语义排序取第一个可行模板，相似度=goal↔模板余弦（驱动 τ 阈值判命中）。
    - 无 query_vec（TEI 不可达/桩）：确定性「第一个可行」兜底，相似度记 1.0（视为命中，沿用 A1）。
    """
    if query_vec is not None:
        for tpl in await repo.rank_plan_templates_by_goal(session, query_vec, limit=10):
            if _feasible(tpl, available):
                emb = tpl.embedding
                # pgvector 取回是 numpy 数组，须显式 is not None（数组真值有歧义）
                sim = _cosine(query_vec, list(emb)) if emb is not None else 1.0
                return tpl, sim
    for tpl in await repo.list_plan_templates(session):
        if _feasible(tpl, available):
            return tpl, 1.0
    return None, 0.0


def _fill_template(tpl: PlanTemplate, goal: str) -> PlanDag:
    """拷贝模板骨架、填入 goal，构造 PlanDag。"""
    skeleton = copy.deepcopy(tpl.dag_skeleton)
    skeleton["goal"] = goal
    return PlanDag.model_validate(skeleton)


async def _generate_dag(
    session: AsyncSession,
    goal: str,
    available: set[str],
    query_vec: list[float],
    gateway: ModelGateway,
) -> PlanDag:
    """模板未命中 → RAG 接地 LLM 生成（A2）。范例取 top-k 最相似模板骨架。"""
    from polis.modules.planner.generator import generate_dag

    model = await resolve_model(session, get_settings().default_chat_model)
    exemplars = [
        t.dag_skeleton
        for t in await repo.rank_plan_templates_by_goal(session, query_vec, limit=_EXEMPLAR_K)
    ]
    return await generate_dag(gateway, model, goal, available, exemplars)


async def plan(
    session: AsyncSession,
    org_id: uuid.UUID,
    goal: str,
    *,
    gateway: ModelGateway | None = None,
) -> PlanResult:
    # ① 当前公司可用能力集（所有 active Agent 的能力并集）
    available = await repo.available_capabilities(session, org_id)
    if not available:
        # 无 active 能力 → 模板/生成都无从满足 → 404（design §14.6 错误矩阵）
        raise NoTemplateMatch

    query_vec = await _embed_goal(goal, gateway)
    chosen, sim = await _retrieve_template(session, available, query_vec)

    # ② 命中模板（相似度达阈值，或无向量时的确定性兜底）→ 填模板；否则 RAG 生成
    if chosen is not None and (query_vec is None or sim >= TAU_TPL):
        dag = _fill_template(chosen, goal)
        template_name: str = chosen.name
        version: str | None = chosen.version
    elif query_vec is not None and gateway is not None:
        # 未命中（无可行模板 / 相似度不足）+ 具备生成条件 → A2 生成（内部已双校验+自修复）
        dag = await _generate_dag(session, goal, available, query_vec, gateway)
        template_name = "generated"
        version = None
    elif chosen is not None:
        # 无生成条件（如 TEI/LLM 不可达）但有可行模板 → 降级用模板（design §14.6）
        dag = _fill_template(chosen, goal)
        template_name = chosen.name
        version = chosen.version
    else:
        raise NoTemplateMatch

    # ③ 确定性校验（生成路径已内部校验，这里对模板路径兜底 + 统一闸）
    vr = validate(dag, available)
    if not vr.ok:
        raise PlanInvalid(vr.errors)

    # ④ 路由/编配（§5.2）：现有 Agent 检索命中即用；无则拼已审 Skill 成 Agent（A3）
    routing = await route_or_compose(session, org_id, dag)

    # ⑤ 持久化
    cost = estimate_cost_cents(dag)
    row = await repo.create_plan(
        session,
        org_id=org_id,
        goal=goal,
        dag=dag.model_dump(),
        version=version,
        estimated_cost_cents=cost,
    )

    # ⑥ 返回
    return PlanResult(
        id=row.id,
        goal=goal,
        status=row.status,
        template=template_name,
        estimated_cost_cents=cost,
        dag=dag,
        routing=routing,
    )
