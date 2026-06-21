"""observability 数据访问层：Run Manifest（可复现快照）。集中 SQL（12 C 分层）。"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from polis.db.org_scoped import select_org_scoped
from polis.modules.memory.models import ResultEnvelope
from polis.modules.observability.models import Approval, RunManifest


async def create_run_manifest(
    session: AsyncSession,
    *,
    task_id: uuid.UUID,
    org_id: uuid.UUID,
    plan_snapshot: dict[str, Any],
    plan_version: str | None,
    models_used: dict[str, Any],
    agents_used: dict[str, Any] | None = None,
    skills_used: dict[str, Any] | None = None,
) -> RunManifest:
    """任务启动时落一份可复现快照（design 06 §5）。"""
    manifest = RunManifest(
        task_id=task_id,
        org_id=org_id,
        started_at=datetime.now(UTC),
        plan_snapshot=plan_snapshot,
        plan_version=plan_version,
        models_used=models_used,
        agents_used=agents_used,
        skills_used=skills_used,
    )
    session.add(manifest)
    await session.flush()
    return manifest


async def get_run_manifest(
    session: AsyncSession, org_id: uuid.UUID, task_id: uuid.UUID
) -> RunManifest | None:
    q = select_org_scoped(RunManifest, org_id).where(RunManifest.task_id == task_id)
    manifest: RunManifest | None = await session.scalar(q)
    return manifest


# ── 审批收件箱（design 06 §6）──────────────────────────────────────────────────


async def get_envelopes_by_task(
    session: AsyncSession, org_id: uuid.UUID, task_id: uuid.UUID
) -> list[ResultEnvelope]:
    """任务的节点产出（result_envelope，按时间正序）。观测页用（TD-028 后可按任务聚合）。"""
    q = (
        select_org_scoped(ResultEnvelope, org_id)
        .where(ResultEnvelope.task_id == task_id)
        .order_by(ResultEnvelope.created_at)
    )
    return list((await session.scalars(q)).all())


async def create_approval(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    kind: str,
    ref_id: str | None,
    payload: dict[str, Any] | None,
    assignee: uuid.UUID | None = None,
) -> Approval:
    ap = Approval(org_id=org_id, kind=kind, ref_id=ref_id, payload=payload, assignee=assignee)
    session.add(ap)
    await session.flush()
    return ap


async def list_approvals(
    session: AsyncSession, org_id: uuid.UUID, status: str = "pending"
) -> list[Approval]:
    q = select_org_scoped(Approval, org_id).where(Approval.status == status)
    return list((await session.scalars(q)).all())


async def get_approval(
    session: AsyncSession, org_id: uuid.UUID, approval_id: uuid.UUID
) -> Approval | None:
    q = select_org_scoped(Approval, org_id).where(Approval.id == approval_id)
    ap: Approval | None = await session.scalar(q)
    return ap


async def decide_approval(
    session: AsyncSession, ap: Approval, *, approve: bool, decided_by: uuid.UUID
) -> Approval:
    ap.status = "approved" if approve else "rejected"
    ap.decided_by = decided_by
    ap.decided_at = datetime.now(UTC)
    await session.flush()
    return ap
