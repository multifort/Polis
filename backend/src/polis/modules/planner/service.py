"""planner 业务逻辑：模板优先的确定性出图 + 确定性路由（ADR-0006，无 LLM）。

不依赖 web，错误以领域异常抛出，由 api 层翻译为 HTTP。
"""

from __future__ import annotations

import copy
import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from polis.modules.model.gateway import ModelGateway
from polis.modules.planner import repository as repo
from polis.modules.planner.models import PlanTemplate
from polis.modules.planner.router import select_agent
from polis.modules.planner.schemas import PlanDag, PlanResult, estimate_cost_cents, validate

logger = logging.getLogger(__name__)


class NoTemplateMatch(Exception):
    """没有任何计划模板的能力需求能被当前公司满足。"""


class PlanInvalid(Exception):
    """模板填充后的 DAG 未通过校验。"""

    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = errors


def _feasible(tpl: PlanTemplate, available: set[str]) -> bool:
    """模板所有节点的能力需求是否 ⊆ 当前公司可用能力集。"""
    nodes = tpl.dag_skeleton.get("nodes", [])
    needs = {c for n in nodes for c in n.get("required_capabilities", [])}
    return needs <= available


async def _embed_goal(goal: str, gateway: ModelGateway | None) -> list[float] | None:
    """把 goal 向量化（A1 语义检索用）。无网关/桩/服务不可达 → None（调用方回退确定性）。"""
    if gateway is None:
        return None
    try:
        return (await gateway.embed([goal]))[0]
    except Exception:  # 检索是增强项，embedding 失败不应让出图崩；记日志后回退
        logger.warning("goal embedding 失败，回退确定性模板选择", exc_info=True)
        return None


async def _select_template(
    session: AsyncSession, available: set[str], goal: str, gateway: ModelGateway | None
) -> PlanTemplate | None:
    """选模板：语义优先（goal↔模板向量最相似的可行模板），否则确定性「第一个可行」兜底（A1）。"""
    query_vec = await _embed_goal(goal, gateway)
    if query_vec is not None:
        for tpl in await repo.rank_plan_templates_by_goal(session, query_vec):
            if _feasible(tpl, available):
                return tpl  # 语义最相似的可行模板
        # 语义候选都不可行（或模板未回填 embedding）→ 落确定性兜底
    for tpl in await repo.list_plan_templates(session):
        if _feasible(tpl, available):
            return tpl
    return None


async def plan(
    session: AsyncSession,
    org_id: uuid.UUID,
    goal: str,
    *,
    embed_gateway: ModelGateway | None = None,
) -> PlanResult:
    # ① 当前公司可用能力集（所有 active Agent 的能力并集）
    available = await repo.available_capabilities(session)

    # ② 选模板：A1 语义优先（按 goal 相似度），TEI 不可用/未注入网关 → 确定性「第一个可行」兜底
    chosen = await _select_template(session, available, goal, embed_gateway)
    if chosen is None:
        raise NoTemplateMatch

    # ③ 拷贝骨架、填入 goal，构造 PlanDag
    skeleton = copy.deepcopy(chosen.dag_skeleton)
    skeleton["goal"] = goal
    dag = PlanDag.model_validate(skeleton)

    # ④ 校验
    vr = validate(dag, available)
    if not vr.ok:
        raise PlanInvalid(vr.errors)

    # ⑤ 对每个 agent 节点（且有能力需求）做确定性路由
    routing: dict[str, str | None] = {}
    for node in dag.nodes:
        if node.type == "agent" and node.required_capabilities:
            agent = await select_agent(session, node.required_capabilities)
            routing[node.id] = agent.name if agent is not None else None

    # ⑥ 持久化
    cost = estimate_cost_cents(dag)
    row = await repo.create_plan(
        session,
        org_id=org_id,
        goal=goal,
        dag=dag.model_dump(),
        version=chosen.version,
        estimated_cost_cents=cost,
    )

    # ⑦ 返回
    return PlanResult(
        id=row.id,
        goal=goal,
        status=row.status,
        template=chosen.name,
        estimated_cost_cents=cost,
        dag=dag,
        routing=routing,
    )
