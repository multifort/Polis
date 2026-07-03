"""审批收件箱 API（design 06 §6/§7）：统一「待我处理」队列 + 决定回写。

四类人审（plan/dangerous_action/provision_review/skill_review/rework）统一进 approval；
决定后更新 status + best-effort 触发 Temporal signal 恢复对应 Workflow。
"""

from __future__ import annotations

import logging
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from polis.config import get_settings
from polis.db.session import get_session
from polis.modules.model.gateway import StubModelGateway, resolve_model
from polis.modules.model.litellm_gateway import LiteLLMGateway
from polis.modules.observability import evaluator
from polis.modules.observability import repository as repo
from polis.modules.observability.audit import write_audit
from polis.modules.org.deps import CurrentOrg, CurrentUserId, OrgContext, require_role

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["approval"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
ApproverOrg = Annotated[OrgContext, Depends(require_role("owner", "approver"))]

_KINDS = {"plan", "dangerous_action", "provision_review", "skill_review", "rework"}


class ApprovalIn(BaseModel):
    kind: str = Field(min_length=1)
    ref_id: str | None = None
    payload: dict[str, Any] | None = None


class ApprovalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    kind: str
    ref_id: str | None
    payload: dict[str, Any] | None
    status: str


class DecideIn(BaseModel):
    approve: bool
    note: str | None = None


@router.post("/approvals", response_model=ApprovalOut, status_code=status.HTTP_201_CREATED)
async def create_approval(data: ApprovalIn, org: CurrentOrg, session: SessionDep) -> ApprovalOut:
    """创建一条待审（通常由系统在危险动作/计划确认/生成审核/返工时调用）。"""
    if data.kind not in _KINDS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"非法 kind：{data.kind}")
    ap = await repo.create_approval(
        session, org_id=org.org_id, kind=data.kind, ref_id=data.ref_id, payload=data.payload
    )
    return ApprovalOut.model_validate(ap)


@router.get("/approvals", response_model=list[ApprovalOut])
async def list_approvals(
    org: CurrentOrg, session: SessionDep, status: str = "pending"
) -> list[ApprovalOut]:
    """统一「待我处理」队列。"""
    rows = await repo.list_approvals(session, org.org_id, status)
    return [ApprovalOut.model_validate(a) for a in rows]


@router.post("/approvals/{approval_id}/decide", response_model=ApprovalOut)
async def decide_approval(
    approval_id: uuid.UUID,
    data: DecideIn,
    org: ApproverOrg,
    user_id: CurrentUserId,
    session: SessionDep,
) -> ApprovalOut:
    """审批决定（owner/approver）：更新 status + 审计 + best-effort 触发 workflow signal。"""
    ap = await repo.get_approval(session, org.org_id, approval_id)
    if ap is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "审批项不存在")
    if ap.status != "pending":
        raise HTTPException(status.HTTP_409_CONFLICT, f"已决定（{ap.status}）")

    # 人审通过 skill_review → 发布草稿 Skill（TD-032 生成停点的放行：published/verified）
    if data.approve and ap.kind == "skill_review" and ap.ref_id:
        from polis.modules.planner.skillgen import publish_skill

        if not await publish_skill(session, org.org_id, uuid.UUID(ap.ref_id)):
            raise HTTPException(status.HTTP_409_CONFLICT, "Skill 未满足发布条件")

    await repo.decide_approval(session, ap, approve=data.approve, decided_by=user_id)
    await write_audit(
        session,
        action="approval.decide",
        actor=str(user_id),
        org_id=org.org_id,
        target=str(approval_id),
        detail={"approve": data.approve, "kind": ap.kind},
    )

    # best-effort：approve 且 payload 关联 workflow → signal 恢复（Temporal 不可达不阻断决定）
    if data.approve and ap.payload and ap.payload.get("workflow_id") and ap.payload.get("node_id"):
        await _try_signal(ap.payload["workflow_id"], ap.payload["node_id"])

    return ApprovalOut.model_validate(ap)


class EvalRunIn(BaseModel):
    output: str
    acceptance_criteria: str | None = None
    expected_fields: list[str] | None = None


class EvalRunOut(BaseModel):
    passed: bool
    assertions_ok: bool
    judge_score: float


@router.post("/eval/run", response_model=EvalRunOut)
async def eval_run(data: EvalRunIn, org: CurrentOrg, session: SessionDep) -> EvalRunOut:
    """评测一条产出（断言 + LLM-judge）。judge 用系统默认模型（有 Key→真实，否则桩）。"""
    settings = get_settings()
    model = await resolve_model(session, settings.default_chat_model)
    gateway = LiteLLMGateway() if settings.deepseek_api_key else StubModelGateway()
    result = await evaluator.score(
        gateway,
        model,
        data.output,
        expected_fields=data.expected_fields,
        acceptance_criteria=data.acceptance_criteria,
    )
    return EvalRunOut(
        passed=result.passed,
        assertions_ok=result.assertions_ok,
        judge_score=result.judge_score,
    )


async def _try_signal(workflow_id: str, node_id: str) -> None:
    import asyncio

    from polis.config import get_settings
    from polis.modules.planner.workflow import TaskWorkflow

    try:
        from temporalio.client import Client

        client = await asyncio.wait_for(Client.connect(get_settings().temporal_addr), timeout=5.0)
        handle = client.get_workflow_handle(workflow_id)
        await handle.signal(TaskWorkflow.approve, node_id)
    except Exception:  # noqa: BLE001 - 编排不可达不阻断审批决定
        logger.debug("approval decide 后 signal 失败（编排不可达），状态已更新")
