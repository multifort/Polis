"""planner 业务逻辑：模板优先的确定性出图 + 确定性路由（ADR-0006，无 LLM）。

不依赖 web，错误以领域异常抛出，由 api 层翻译为 HTTP。
"""

from __future__ import annotations

import copy
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from polis.modules.planner import repository as repo
from polis.modules.planner.router import select_agent
from polis.modules.planner.schemas import PlanDag, PlanResult, estimate_cost_cents, validate


class NoTemplateMatch(Exception):
    """没有任何计划模板的能力需求能被当前公司满足。"""


class PlanInvalid(Exception):
    """模板填充后的 DAG 未通过校验。"""

    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = errors


async def plan(session: AsyncSession, org_id: uuid.UUID, goal: str) -> PlanResult:
    # ① 当前公司可用能力集（所有 active Agent 的能力并集）
    available = await repo.available_capabilities(session)

    # ② 选第一个所有节点能力需求都 ⊆ 可用能力集的模板
    chosen = None
    for tpl in await repo.list_plan_templates(session):
        nodes = tpl.dag_skeleton.get("nodes", [])
        needs = {c for n in nodes for c in n.get("required_capabilities", [])}
        if needs <= available:
            chosen = tpl
            break
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
