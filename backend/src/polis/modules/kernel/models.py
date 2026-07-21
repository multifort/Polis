"""Kernel-owned core runtime ORM models.

K0 moves declaration ownership only.  Table names, columns, constraints and
relationships must remain identical to their legacy definitions.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, CheckConstraint, ForeignKey, Integer, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from polis.db.base import Base
from polis.db.mixins import OrgScopedMixin, TimestampMixin, UUIDPkMixin


class Plan(UUIDPkMixin, OrgScopedMixin, Base):
    __tablename__ = "plan"

    goal: Mapped[str | None] = mapped_column(Text)
    dag: Mapped[dict[str, Any]] = mapped_column(JSONB)
    version: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default="draft")
    estimated_cost_cents: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))

    __table_args__ = (
        CheckConstraint(
            "status IN ('draft','approved','running','done','failed','needs_review')",
            name="status",
        ),
    )


class TaskRun(UUIDPkMixin, OrgScopedMixin, TimestampMixin, Base):
    """Existing task execution anchor; K4 evolves it additively into ExecutionRun."""

    __tablename__ = "task_run"

    task_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("task.id"))
    plan_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("plan.id"))
    temporal_workflow_id: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default="pending")
    priority: Mapped[int] = mapped_column(Integer, server_default="0")
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','running','paused','done','failed','needs_review')",
            name="status",
        ),
    )


class RunManifest(OrgScopedMixin, Base):
    """Reproducible execution snapshot keyed by the existing task run id."""

    __tablename__ = "run_manifest"

    task_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("task_run.id", ondelete="CASCADE"), primary_key=True
    )
    started_at: Mapped[datetime | None]
    agents_used: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    skills_used: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    models_used: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    plan_version: Mapped[str | None] = mapped_column(Text)
    plan_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class Approval(UUIDPkMixin, OrgScopedMixin, Base):
    __tablename__ = "approval"

    kind: Mapped[str] = mapped_column(Text)
    ref_id: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(Text, server_default="pending")
    assignee: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id"))
    decided_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id"))
    decided_at: Mapped[datetime | None]

    __table_args__ = (
        CheckConstraint(
            "kind IN ('plan','dangerous_action','provision_review','skill_review','rework')",
            name="kind",
        ),
        CheckConstraint("status IN ('pending','approved','rejected')", name="status"),
    )


class ResultEnvelope(UUIDPkMixin, OrgScopedMixin, Base):
    __tablename__ = "result_envelope"

    task_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("task_run.id"))
    node_id: Mapped[str | None] = mapped_column(Text)
    agent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agent.id"))
    status: Mapped[str | None] = mapped_column(Text)
    artifacts: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    facts: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    summary: Mapped[str | None] = mapped_column(Text)
    content: Mapped[str | None] = mapped_column(Text)
    tokens: Mapped[int | None] = mapped_column(Integer)
    needs_human: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))


class ArtifactDescriptor(UUIDPkMixin, OrgScopedMixin, Base):
    __tablename__ = "artifact_descriptor"

    task_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("task_run.id"))
    node_id: Mapped[str | None] = mapped_column(Text)
    modality: Mapped[str | None] = mapped_column(Text)
    uri: Mapped[str | None] = mapped_column(Text)
    mime: Mapped[str | None] = mapped_column(Text)
    caption: Mapped[str | None] = mapped_column(Text)
    provenance: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    meta: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))


__all__ = [
    "Approval",
    "ArtifactDescriptor",
    "Plan",
    "ResultEnvelope",
    "RunManifest",
    "TaskRun",
]
