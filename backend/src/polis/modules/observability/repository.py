"""observability 数据访问层：Run Manifest（可复现快照）。集中 SQL（12 C 分层）。"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from polis.db.org_scoped import select_org_scoped
from polis.modules.observability.models import RunManifest


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
