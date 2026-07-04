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
from polis.modules.planner.models import (
    Capability,
    Plan,
    PlanTemplate,
    SceneCategory,
    Task,
    TaskRun,
)
from polis.modules.runtime.models import Skill

# 任务级附件：登记为 artifact_descriptor(modality='file')；归属任务记 meta（task_id 列 FK→task_run，
# 附件在 run 前不属任何 run，故列置 NULL，用 meta.owner_task_id 关联可复用任务）。
ATTACHMENT_KIND = "attachment"


def plan_template_semantic_text(dag: dict[str, Any], fallback_name: str) -> str:
    """计划模板的语义检索文本：聚合验收标准 + 节点输入/产出提示。

    与 embed_backfill 保持同一口径，确保用户新沉淀模板的即时 embedding 与批量回填一致。
    """
    parts: list[str] = [str(dag.get("acceptance_criteria") or "")]
    for node in dag.get("nodes", []):
        if not isinstance(node, dict):
            continue
        parts.append(str(node.get("input_hint") or ""))
        parts.append(str(node.get("expected_output") or ""))
    text = " ".join(p for p in parts if p).strip()
    return text or fallback_name


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
    status: str = "running",
    priority: int = 0,
) -> TaskRun:
    now = datetime.now(UTC) if status == "running" else None
    run = TaskRun(
        org_id=org_id,
        task_id=task_id,  # V2-P1：关联可复用任务（nullable，兼容直接出图的旧/临时运行）
        plan_id=plan_id,
        temporal_workflow_id=temporal_workflow_id,
        status=status,
        priority=priority,
        started_at=now,
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


async def delete_task(session: AsyncSession, org_id: uuid.UUID, task_id: uuid.UUID) -> bool:
    """删除任务及其 task_runs（级联）。"""
    task = await get_task(session, org_id, task_id)
    if task is None:
        return False
    # 先删关联的 task_runs
    from sqlalchemy import delete as sqla_delete

    await session.execute(
        sqla_delete(TaskRun).where(TaskRun.task_id == task_id, TaskRun.org_id == org_id)
    )
    await session.delete(task)
    await session.flush()
    return True


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
    """org 已完成运行的平均耗时（秒）。

    优先用 task_run.started_at/finished_at（TD-019 已部分偿还，终态回写已落地）；
    旧行可能仍为 NULL，此时用 result_envelope.created_at(min/max) 兜底。
    """
    from sqlalchemy import func

    avg = await session.scalar(
        select(func.avg(func.extract("epoch", TaskRun.finished_at - TaskRun.started_at))).where(
            TaskRun.org_id == org_id,
            TaskRun.started_at.isnot(None),
            TaskRun.finished_at.isnot(None),
        )
    )
    if avg is not None:
        return float(avg)

    # 兜底：用节点产出的 min/max created_at 近似时长（与 observability 口径一致）
    from polis.modules.memory.models import ResultEnvelope

    run_rows = (
        await session.execute(
            select(TaskRun.id).where(
                TaskRun.org_id == org_id,
                TaskRun.status.in_(("done", "failed", "needs_review")),
            )
        )
    ).all()
    if not run_rows:
        return None

    durations: list[float] = []
    for (run_id,) in run_rows:
        times = (
            await session.execute(
                select(
                    func.min(ResultEnvelope.created_at),
                    func.max(ResultEnvelope.created_at),
                ).where(ResultEnvelope.task_id == run_id)
            )
        ).first()
        if times and times[0] and times[1]:
            dur = (times[1] - times[0]).total_seconds()
            if dur > 0:
                durations.append(dur)

    if not durations:
        return None
    return sum(durations) / len(durations)


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


async def next_pending_runs(
    session: AsyncSession, org_id: uuid.UUID, limit: int = 1
) -> list[TaskRun]:
    """S3 自动 dequeue：按优先级取 pending run。

    优先级规则：显式 priority 越大越优先；同 priority 短作业优先
    （plan.estimated_cost_cents 升序）；再同成本按入队时间 FIFO。
    """
    if limit <= 0:
        return []
    rows = await session.scalars(
        select_org_scoped(TaskRun, org_id)
        .outerjoin(Plan, Plan.id == TaskRun.plan_id)
        .where(TaskRun.status == "pending")
        .order_by(
            TaskRun.priority.desc(),
            Plan.estimated_cost_cents.asc().nulls_last(),
            TaskRun.created_at.asc(),
        )
        .limit(limit)
    )
    return list(rows.all())


async def next_pending_run(session: AsyncSession, org_id: uuid.UUID) -> TaskRun | None:
    """S3 自动 dequeue：兼容旧单槽调用，返回当前最高优先级 pending run。"""
    runs = await next_pending_runs(session, org_id, limit=1)
    return runs[0] if runs else None


async def mark_task_run_running(session: AsyncSession, run: TaskRun, workflow_id: str) -> TaskRun:
    """把 pending run 切为 running，并记录真正启动的 Temporal workflow id。"""
    run.status = "running"
    run.temporal_workflow_id = workflow_id
    run.started_at = datetime.now(UTC)
    if run.plan_id is not None:
        await update_plan_status(session, run.org_id, run.plan_id, "running")
    await session.flush()
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


async def delete_task_run(session: AsyncSession, run: TaskRun) -> None:
    """删除一条 task_run（如 approve 时清理旧的 pending run）。"""
    await session.delete(run)
    await session.flush()


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
    embedding: list[float] | None = None,
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
        if embedding is not None:
            existing.embedding = embedding
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
        embedding=embedding,
    )
    session.add(tpl)
    await session.flush()
    return tpl


# ── R3/P5 场景分类管理 ───────────────────────────────────────────────


async def list_scene_categories(session: AsyncSession, org_id: uuid.UUID) -> list[SceneCategory]:
    """场景库分类列表：平台内置(org_id=NULL) ∪ 本 org 私有。"""
    from sqlalchemy import or_

    q = (
        select(SceneCategory)
        .where(or_(SceneCategory.org_id.is_(None), SceneCategory.org_id == org_id))
        .order_by(SceneCategory.domain, SceneCategory.display_order)
    )
    return list((await session.scalars(q)).all())


async def create_scene_category(
    session: AsyncSession,
    org_id: uuid.UUID,
    domain: str,
    subcategory: str | None = None,
) -> SceneCategory:
    import uuid as _uuid

    cat = SceneCategory(id=_uuid.uuid4(), org_id=org_id, domain=domain, subcategory=subcategory)
    session.add(cat)
    await session.flush()
    return cat


async def update_scene_category(
    session: AsyncSession,
    org_id: uuid.UUID,
    category_id: uuid.UUID,
    domain: str,
    subcategory: str | None,
) -> SceneCategory | None:
    cat = await session.scalar(
        select(SceneCategory).where(SceneCategory.id == category_id, SceneCategory.org_id == org_id)
    )
    if cat is None:
        return None
    cat.domain = domain
    cat.subcategory = subcategory
    await session.flush()
    return cat


async def delete_scene_category(
    session: AsyncSession, org_id: uuid.UUID, category_id: uuid.UUID
) -> dict[str, Any] | None:
    """删除私有分类及其关联的模板。返回 {domain, subcategory, deleted_templates: int} 或 None。"""
    cat = await session.scalar(
        select(SceneCategory).where(SceneCategory.id == category_id, SceneCategory.org_id == org_id)
    )
    if cat is None:
        return None

    # 级联删除该分类下的模板（匹配 domain + subcategory）
    # 若删除的是大类（无 subcategory），一并删除其所有子类
    from sqlalchemy import delete as sqla_delete

    if cat.subcategory:
        tpl_cond: list[Any] = [
            PlanTemplate.domain == cat.domain,
            PlanTemplate.subcategory == cat.subcategory,
            PlanTemplate.owner_org_id == org_id,
        ]
    else:
        # 大类：删除该 domain 下所有模板 + 所有子类 category
        await session.execute(
            sqla_delete(SceneCategory).where(
                SceneCategory.domain == cat.domain,
                SceneCategory.subcategory.isnot(None),
                SceneCategory.org_id == org_id,
            )
        )
        tpl_cond = [
            PlanTemplate.domain == cat.domain,
            PlanTemplate.owner_org_id == org_id,
        ]
    result = await session.execute(sqla_delete(PlanTemplate).where(*tpl_cond))
    deleted_tpls: int = getattr(result, "rowcount", 0) or 0

    await session.delete(cat)
    await session.flush()
    return {"domain": cat.domain, "subcategory": cat.subcategory, "deleted_templates": deleted_tpls}
