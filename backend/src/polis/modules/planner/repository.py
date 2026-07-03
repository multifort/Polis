"""planner 数据访问层。集中 SQL，service 只调这里（12 C 分层）。"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from polis.db.org_scoped import select_org_scoped, visible_clause
from polis.modules.memory.models import ArtifactDescriptor
from polis.modules.org.models import Agent, AgentCapability
from polis.modules.planner.models import Capability, Plan, PlanTemplate, Task, TaskRun
from polis.modules.runtime.models import Skill

# 任务级附件：登记为 artifact_descriptor(modality='file')；归属任务记 meta（task_id 列 FK→task_run，
# 附件在 run 前不属任何 run，故列置 NULL，用 meta.owner_task_id 关联可复用任务）。
ATTACHMENT_KIND = "attachment"


async def available_capabilities(session: AsyncSession, org_id: uuid.UUID) -> set[str]:
    """当前公司可用能力集 = active Agent 能力 ∪ 可见 published Skill 能力（ADR-0009）。

    能力的「信用」来自实现它的 Skill 过审+发布；故 published Skill 提供的能力也算 active——
    即便暂无 Agent 承接，编配器可按需拼 Skill 成 Agent（A3 route_or_compose）。
    """
    agent_rows = await session.execute(
        select(AgentCapability.capability)
        .join(Agent, Agent.id == AgentCapability.agent_id)
        .where(Agent.status == "active")
    )
    skill_rows = await session.execute(
        select(Skill.capability).where(
            Skill.capability.is_not(None),
            Skill.status == "published",
            visible_clause(Skill, org_id),
        )
    )
    return {c for (c,) in agent_rows.all()} | {c for (c,) in skill_rows.all() if c}


async def list_plan_templates(session: AsyncSession, org_id: uuid.UUID) -> list[PlanTemplate]:
    """可见计划模板（自己私有 ∪ 公共，V2-R1），按 name/version 稳定排序。

    R3 引入私有(用户存为模板)后，不加可见性过滤会跨租户泄露——必须走 select_visible。
    """
    q = visible_clause(PlanTemplate, org_id)
    return list(
        (
            await session.scalars(
                select(PlanTemplate).where(q).order_by(PlanTemplate.name, PlanTemplate.version)
            )
        ).all()
    )


async def rank_capabilities_by_vector(
    session: AsyncSession, query_embedding: list[float], limit: int = 5
) -> list[tuple[Capability, float]]:
    """按向量与 capability.embedding 余弦排序（TD-030 能力语义去重 §14.4）。返回 (能力, 相似度)。

    仅含 embedding 非空的能力；相似度 = 1 - cosine_distance。供 activate_capability 把拟新增能力
    解析到最近的已有 key（防 report.gen/report.make 同义爆炸）。
    """
    dist = Capability.embedding.cosine_distance(query_embedding)
    rows = (
        await session.execute(
            select(Capability, dist)
            .where(Capability.embedding.isnot(None))
            .order_by(dist)
            .limit(limit)
        )
    ).all()
    return [(c, 1.0 - float(d)) for c, d in rows]


async def rank_plan_templates_by_goal(
    session: AsyncSession, org_id: uuid.UUID, query_embedding: list[float], limit: int = 10
) -> list[PlanTemplate]:
    """按 goal 向量与模板 embedding 的余弦距离升序返回候选模板（A1 语义检索）。

    仅含 embedding 非空的模板（未回填的走 service 兜底确定性路径）；用 hnsw 索引。
    可见性过滤（V2-R1/R3）：自己私有 ∪ 公共，不泄露他 org 私有场景模板。
    """
    q = (
        select(PlanTemplate)
        .where(PlanTemplate.embedding.isnot(None), visible_clause(PlanTemplate, org_id))
        .order_by(PlanTemplate.embedding.cosine_distance(query_embedding))
        .limit(limit)
    )
    return list((await session.scalars(q)).all())


async def create_plan(
    session: AsyncSession,
    org_id: uuid.UUID,
    goal: str,
    dag: dict[str, Any],
    version: str | None,
    estimated_cost_cents: int,
) -> Plan:
    plan = Plan(
        org_id=org_id,
        goal=goal,
        dag=dag,
        version=version,
        status="draft",
        estimated_cost_cents=estimated_cost_cents,
    )
    session.add(plan)
    await session.flush()
    return plan


async def get_plan(session: AsyncSession, org_id: uuid.UUID, plan_id: uuid.UUID) -> Plan | None:
    """按 ID 取计划。RLS 已限定 org，叠加应用层 org_id 过滤做纵深防御（TD-015）。"""
    plan: Plan | None = await session.scalar(
        select_org_scoped(Plan, org_id).where(Plan.id == plan_id)
    )
    return plan


async def update_plan_status(
    session: AsyncSession, org_id: uuid.UUID, plan_id: uuid.UUID, new_status: str
) -> None:
    plan = await get_plan(session, org_id, plan_id)
    if plan is not None:
        plan.status = new_status
        await session.flush()


async def create_task_run(
    session: AsyncSession,
    org_id: uuid.UUID,
    plan_id: uuid.UUID,
    temporal_workflow_id: str,
    task_id: uuid.UUID | None = None,
) -> TaskRun:
    run = TaskRun(
        org_id=org_id,
        task_id=task_id,  # V2-P1：关联可复用任务（nullable，兼容直接出图的旧/临时运行）
        plan_id=plan_id,
        temporal_workflow_id=temporal_workflow_id,
        status="running",
    )
    session.add(run)
    await session.flush()
    return run


# ── 任务实体（V2-P1）──────────────────────────────────────────────────────────


async def create_task(
    session: AsyncSession,
    org_id: uuid.UUID,
    *,
    name: str,
    goal: str,
    scenario_ref: str | None = None,
    input_schema: dict[str, Any] | None = None,
    inputs: dict[str, Any] | None = None,
    created_by: uuid.UUID | None = None,
) -> Task:
    task = Task(
        org_id=org_id,
        name=name,
        goal=goal,
        scenario_ref=scenario_ref,
        input_schema=input_schema,
        inputs=inputs,
        created_by=created_by,
    )
    session.add(task)
    await session.flush()
    return task


async def list_tasks(session: AsyncSession, org_id: uuid.UUID) -> list[Task]:
    q = select_org_scoped(Task, org_id).order_by(Task.created_at.desc())
    return list((await session.scalars(q)).all())


async def get_task(session: AsyncSession, org_id: uuid.UUID, task_id: uuid.UUID) -> Task | None:
    t: Task | None = await session.scalar(select_org_scoped(Task, org_id).where(Task.id == task_id))
    return t


async def create_attachment(
    session: AsyncSession,
    org_id: uuid.UUID,
    *,
    task_id: uuid.UUID,
    filename: str,
    uri: str,
    mime: str | None,
    size: int,
    uploaded_by: uuid.UUID | None = None,
    field: str | None = None,
) -> ArtifactDescriptor:
    """登记一个任务附件（覆盖同名：先删旧行再插，与 MinIO 覆盖语义一致）。"""
    existing = await get_attachment(session, org_id, task_id, filename)
    if existing is not None:
        await session.delete(existing)
        await session.flush()
    meta: dict[str, Any] = {
        "kind": ATTACHMENT_KIND,
        "owner_task_id": str(task_id),
        "filename": filename,
        "size": size,
    }
    if field:
        meta["field"] = field
    art = ArtifactDescriptor(
        org_id=org_id,
        task_id=None,  # 列 FK→task_run；任务级附件在 run 前，归属记 meta.owner_task_id
        modality="file",
        uri=uri,
        mime=mime,
        caption=filename,
        provenance={"uploaded_by": str(uploaded_by)} if uploaded_by else None,
        meta=meta,
    )
    session.add(art)
    await session.flush()
    return art


def _attachment_scope(org_id: uuid.UUID, task_id: uuid.UUID) -> Any:
    return select_org_scoped(ArtifactDescriptor, org_id).where(
        ArtifactDescriptor.meta["kind"].astext == ATTACHMENT_KIND,
        ArtifactDescriptor.meta["owner_task_id"].astext == str(task_id),
    )


async def list_attachments(
    session: AsyncSession, org_id: uuid.UUID, task_id: uuid.UUID
) -> list[ArtifactDescriptor]:
    q = _attachment_scope(org_id, task_id).order_by(ArtifactDescriptor.created_at)
    return list((await session.scalars(q)).all())


async def get_attachment(
    session: AsyncSession, org_id: uuid.UUID, task_id: uuid.UUID, filename: str
) -> ArtifactDescriptor | None:
    q = _attachment_scope(org_id, task_id).where(
        ArtifactDescriptor.meta["filename"].astext == filename
    )
    a: ArtifactDescriptor | None = await session.scalar(q)
    return a


async def delete_attachment(
    session: AsyncSession, org_id: uuid.UUID, task_id: uuid.UUID, filename: str
) -> bool:
    a = await get_attachment(session, org_id, task_id, filename)
    if a is None:
        return False
    await session.delete(a)
    await session.flush()
    return True


async def create_export_artifact(
    session: AsyncSession,
    org_id: uuid.UUID,
    *,
    run_id: uuid.UUID,
    filename: str,
    uri: str,
    mime: str,
    size: int,
    fmt: str,
) -> ArtifactDescriptor:
    """登记一份结果导出产物（V2-P3b）。task_id 直接用 run.id——不同于附件（挂在 task 上），
    导出是**某次运行**的结果，天然落在 artifact_descriptor.task_id（FK→task_run）本意上。
    """
    art = ArtifactDescriptor(
        org_id=org_id,
        task_id=run_id,
        modality="file",
        uri=uri,
        mime=mime,
        caption=filename,
        meta={"kind": "export", "format": fmt, "filename": filename, "size": size},
    )
    session.add(art)
    await session.flush()
    return art


async def list_task_runs(
    session: AsyncSession, org_id: uuid.UUID, task_id: uuid.UUID
) -> list[tuple[TaskRun, int | None]]:
    """返回 (task_run, plan.estimated_cost_cents) 列表。"""

    q = (
        select(TaskRun, Plan.estimated_cost_cents)
        .outerjoin(Plan, Plan.id == TaskRun.plan_id)
        .where(TaskRun.org_id == org_id, TaskRun.task_id == task_id)
        .order_by(TaskRun.created_at.desc())
    )
    rows = (await session.execute(q)).all()
    return [(r, cost) for r, cost in rows]


async def count_active_runs(session: AsyncSession, org_id: uuid.UUID) -> int:
    """org 当前在跑的 task_run 数（S3 并发闸）。"""
    from sqlalchemy import func

    n = await session.scalar(
        select(func.count())
        .select_from(TaskRun)
        .where(TaskRun.org_id == org_id, TaskRun.status == "running")
    )
    return int(n or 0)


async def org_estimated_cost_cents(session: AsyncSession, org_id: uuid.UUID) -> int:
    """org 累计预估成本（分，S3 预算提示用）：所有运行关联 plan 的 estimated_cost_cents 之和。"""
    from sqlalchemy import func

    total = await session.scalar(
        select(func.coalesce(func.sum(Plan.estimated_cost_cents), 0))
        .select_from(TaskRun)
        .join(Plan, Plan.id == TaskRun.plan_id)
        .where(TaskRun.org_id == org_id)
    )
    return int(total or 0)


async def dashboard_status_counts(session: AsyncSession, org_id: uuid.UUID) -> dict[str, int]:
    """org 全部 task_run 按状态分布计数（P4 看板：成功率/吞吐）。"""
    from sqlalchemy import func

    rows = (
        await session.execute(
            select(TaskRun.status, func.count())
            .where(TaskRun.org_id == org_id)
            .group_by(TaskRun.status)
        )
    ).all()
    return {status: int(count) for status, count in rows}


async def dashboard_avg_duration_seconds(session: AsyncSession, org_id: uuid.UUID) -> float | None:
    """org 已完成运行的平均耗时（秒），仅统计 started_at/finished_at 均已回写的行（P4）。"""
    from sqlalchemy import func

    avg = await session.scalar(
        select(func.avg(func.extract("epoch", TaskRun.finished_at - TaskRun.started_at))).where(
            TaskRun.org_id == org_id,
            TaskRun.started_at.isnot(None),
            TaskRun.finished_at.isnot(None),
        )
    )
    return float(avg) if avg is not None else None


async def dashboard_template_distribution(
    session: AsyncSession, org_id: uuid.UUID
) -> list[tuple[str, int, bool]]:
    """按场景(模板)分布：(模板名或'generated', 次数, 是否模板命中)。
    P4 场景分布 + 复用命中率来源。
    """
    from sqlalchemy import func

    # 按原始（可空）version 分组：Postgres 把所有 NULL 聚成一组，天然对应「生成」；
    # 分组表达式与派生名称在 Python 侧处理，避免多表达式 GROUP BY 的严格匹配问题。
    rows = (
        await session.execute(
            select(Plan.version, func.count())
            .select_from(TaskRun)
            .join(Plan, Plan.id == TaskRun.plan_id)
            .where(TaskRun.org_id == org_id)
            .group_by(Plan.version)
            .order_by(func.count().desc())
        )
    ).all()
    return [(version or "generated", int(count), version is not None) for version, count in rows]


async def dashboard_recent_runs(
    session: AsyncSession, org_id: uuid.UUID, limit: int = 50
) -> list[TaskRun]:
    """近期运行（供成本/token 聚合，逐条拉 langfuse，限量避免过慢，P4）。"""
    q = select_org_scoped(TaskRun, org_id).order_by(TaskRun.created_at.desc()).limit(limit)
    return list((await session.scalars(q)).all())


async def get_task_run(
    session: AsyncSession, org_id: uuid.UUID, run_id: uuid.UUID
) -> TaskRun | None:
    run: TaskRun | None = await session.scalar(
        select_org_scoped(TaskRun, org_id).where(TaskRun.id == run_id)
    )
    return run


async def get_task_run_by_plan(
    session: AsyncSession, org_id: uuid.UUID, plan_id: uuid.UUID
) -> TaskRun | None:
    run: TaskRun | None = await session.scalar(
        select_org_scoped(TaskRun, org_id)
        .where(TaskRun.plan_id == plan_id)
        .order_by(TaskRun.created_at.desc())
    )
    return run


async def list_workspace_runs(
    session: AsyncSession, org_id: uuid.UUID, *, active_limit: int = 6, recent_limit: int = 6
) -> tuple[
    list[tuple[TaskRun, Task | None, int, int | None]],
    list[tuple[TaskRun, Task | None, int, int | None]],
]:
    """工作台用：活跃运行（running/pending） + 最近完成（done/failed/needs_review）。

    分别返回 (task_run, task_or_none, node_count, estimated_cost_cents) 列表。
    活跃按 started_at 降序（最近先启动），完成按 finished_at 降序（最近先完成）。
    """
    # 活跃运行：left join task + plan 补名称/目标/节点数/成本
    active_q = (
        select(TaskRun, Task, Plan.estimated_cost_cents, Plan.dag)
        .outerjoin(Task, Task.id == TaskRun.task_id)
        .outerjoin(Plan, Plan.id == TaskRun.plan_id)
        .where(
            TaskRun.org_id == org_id,
            TaskRun.status.in_(("running", "pending")),
        )
        .order_by(TaskRun.started_at.desc().nullslast(), TaskRun.created_at.desc())
        .limit(active_limit)
    )
    active_rows = (await session.execute(active_q)).all()

    # 最近完成
    recent_q = (
        select(TaskRun, Task, Plan.estimated_cost_cents, Plan.dag)
        .outerjoin(Task, Task.id == TaskRun.task_id)
        .outerjoin(Plan, Plan.id == TaskRun.plan_id)
        .where(
            TaskRun.org_id == org_id,
            TaskRun.status.in_(("done", "failed", "needs_review")),
        )
        .order_by(TaskRun.finished_at.desc().nullslast(), TaskRun.created_at.desc())
        .limit(recent_limit)
    )
    recent_rows = (await session.execute(recent_q)).all()

    def _node_count(dag: Any) -> int:
        if dag is None:
            return 0
        nodes = dag.get("nodes") if isinstance(dag, dict) else []
        return len(nodes) if isinstance(nodes, list) else 0

    active: list[tuple[TaskRun, Task | None, int, int | None]] = [
        (r, t, _node_count(dag), cost) for r, t, cost, dag in active_rows
    ]
    recent: list[tuple[TaskRun, Task | None, int, int | None]] = [
        (r, t, _node_count(dag), cost) for r, t, cost, dag in recent_rows
    ]
    return active, recent


async def finish_task_run(session: AsyncSession, run: TaskRun, new_status: str) -> None:
    """工作流到达终态时回写 task_run + 关联 plan 的状态（保持 DB 与编排一致）。"""
    run.status = new_status
    run.finished_at = datetime.now(UTC)
    if run.plan_id is not None:
        # done/needs_review 原样回写（plan CHECK 已含），其余归 failed
        plan_status = new_status if new_status in ("done", "needs_review") else "failed"
        await update_plan_status(session, run.org_id, run.plan_id, plan_status)
    await session.flush()


async def save_plan_as_template(
    session: AsyncSession,
    org_id: uuid.UUID,
    plan: Plan,
    *,
    name: str,
    domain: str | None = None,
    subcategory: str | None = None,
) -> PlanTemplate:
    """将已有计划的 DAG 存为私有场景模板（R3 场景库飞轮）。

    幂等：同名模板已存在则覆盖（version 递增），同一 org 内 name 唯一。
    """
    existing = (
        await session.scalars(
            select(PlanTemplate).where(
                PlanTemplate.name == name, PlanTemplate.owner_org_id == org_id
            )
        )
    ).first()

    if existing is not None:
        # 覆盖：更新 DAG + bump version
        existing.dag_skeleton = plan.dag
        existing.acceptance_criteria = (
            plan.dag.get("acceptance_criteria") if isinstance(plan.dag, dict) else None
        )
        existing.domain = domain
        existing.subcategory = subcategory
        existing.visibility = "private"
        # bump minor version
        parts = existing.version.split(".")
        try:
            minor = int(parts[-1]) + 1
            existing.version = ".".join(parts[:-1] + [str(minor)])
        except (ValueError, IndexError):
            existing.version = f"{existing.version}.1"
        await session.flush()
        return existing

    tpl = PlanTemplate(
        name=name,
        version="1.0",
        dag_skeleton=plan.dag,
        visibility="private",
        owner_org_id=org_id,
        source="user_saved",
        domain=domain,
        subcategory=subcategory,
        acceptance_criteria=plan.dag.get("acceptance_criteria")
        if isinstance(plan.dag, dict)
        else None,
    )
    session.add(tpl)
    await session.flush()
    return tpl
