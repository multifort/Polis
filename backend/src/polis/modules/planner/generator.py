"""A2 规划生成：RAG 接地的 LLM DAG 生成 + 结构/语义双校验 + 有界自修复（偿还 TD-020）。

设计：docs/design/v2/01 §4.3 / §14.3。退化链里「模板未命中」的兜底——让 LLM 按「最像的
几个模板」为范例生成 DAG，再用确定性 `PlanDag.model_validate`(结构) + `validate`(语义) 双重
把关；校验失败把具体错误反馈回 LLM 驱动有界自修复（N 次）。**LLM 灵活 + 确定性可执行保证**。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import ValidationError

from polis.modules.model.gateway import ChatMessage, ModelGateway, ResolvedModel
from polis.modules.planner.errors import PlanInvalid
from polis.modules.planner.schemas import PlanDag, validate

logger = logging.getLogger(__name__)

MAX_NODES = 12  # 防 LLM 节点膨胀
DEFAULT_ATTEMPTS = 2  # N：含 1 次自修复
DEFAULT_BUDGET_CENTS = 5000  # 生成 DAG 缺省预算闸（LLM 未给时注入）

_SYSTEM = (
    "你是 Polis 的规划师。给定目标，输出一个可执行的工作流 DAG（JSON）。硬规则（必须全部满足）：\n"
    "1) 只能用「可用能力词表」里的能力 key 填 required_capabilities，不得臆造能力；\n"
    "2) DAG 必须无环；每个节点的 deps 只能引用已出现的节点 id；\n"
    "3) 有副作用/危险动作的节点必须是 human 类型（人审 gate），其余分析/生成类用 agent；\n"
    f"4) 节点数 ≤ {MAX_NODES}，保持精简；\n"
    "5) 只输出 JSON，不要解释、不要 markdown 代码围栏。\n"
    "JSON 结构：{workflow_name, goal, acceptance_criteria, budget_cents, nodes:[{id, type, "
    "deps, required_capabilities, executor, input_hint, expected_output, dangerous}]}"
)


def _build_user(
    goal: str,
    available: set[str],
    exemplars: list[dict[str, Any]],
    org_memory: list[str] | None = None,
) -> str:
    caps = "、".join(sorted(available)) or "（无）"
    ex = json.dumps(exemplars[:3], ensure_ascii=False) if exemplars else "（无可参考模板）"
    mem = (
        "公司已知（先验，供约束/取舍，勿照抄）：\n" + "\n".join(f"- {m}" for m in org_memory) + "\n"
        if org_memory
        else ""
    )
    return (
        f"目标：{goal}\n"
        f"可用能力词表（required_capabilities 只能取这些 key）：{caps}\n"
        f"{mem}"
        f"参考范例（最相似的已有模板骨架，照着改，不要照抄）：{ex}\n"
        "请输出严格符合结构的 DAG JSON。"
    )


def _parse_json(raw: str) -> Any:
    """从 LLM 文本里抽 JSON：容忍 ```json 围栏 / 前后噪声，取第一个完整对象。"""
    s = raw.strip()
    if s.startswith("```"):
        s = s.split("```", 2)[1] if s.count("```") >= 2 else s.strip("`")
        if s.lstrip().lower().startswith("json"):
            s = s.lstrip()[4:]
    start, end = s.find("{"), s.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("未找到 JSON 对象")
    return json.loads(s[start : end + 1])


async def generate_dag(
    gateway: ModelGateway,
    model: ResolvedModel,
    goal: str,
    available: set[str],
    exemplars: list[dict[str, Any]],
    *,
    org_memory: list[str] | None = None,
    budget_cents: int = DEFAULT_BUDGET_CENTS,
    attempts: int = DEFAULT_ATTEMPTS,
) -> PlanDag:
    """RAG 接地生成 DAG + 双校验 + 有界自修复。N 次仍不过 → PlanInvalid（最后一轮错误）。

    org_memory（B2）：公司级先验事实，注入 prompt 供生成约束/取舍。
    """
    messages = [ChatMessage(role="system", content=_SYSTEM)]
    user = _build_user(goal, available, exemplars, org_memory)
    last_errors: list[str] = ["生成失败（无有效输出）"]

    for attempt in range(1, attempts + 1):
        messages.append(ChatMessage(role="user", content=user))
        resp = await gateway.chat(model, messages)
        raw = resp.content or ""
        messages.append(ChatMessage(role="assistant", content=raw))

        # ① 结构校验（Pydantic）
        try:
            dag = PlanDag.model_validate(_parse_json(raw))
        except (ValueError, ValidationError) as exc:
            last_errors = [f"输出无法解析为合法 PlanDag JSON：{exc}"]
            user = f"上次输出有误：{last_errors[0]}。请只输出修正后的完整 JSON。"
            logger.info("generate_dag 第 %d 次结构校验失败", attempt)
            continue

        # 缺省预算注入（LLM 未给 → 用缺省闸，保证 validate 的预算检查生效）
        if dag.budget_cents <= 0:
            dag.budget_cents = budget_cents

        # ② 语义校验（复用 V1 validate）+ 节点数上限
        vr = validate(dag, available)
        errs = list(vr.errors)
        if len(dag.nodes) > MAX_NODES:
            errs.append(f"节点数 {len(dag.nodes)} 超过上限 {MAX_NODES}")
        if not errs:
            logger.info("generate_dag 第 %d 次通过（%d 节点）", attempt, len(dag.nodes))
            return dag

        # ③ 错误反馈驱动自修复
        last_errors = errs
        user = "上次生成的 DAG 校验未过：" + "；".join(errs) + "。请修正后重新输出完整 JSON。"
        logger.info("generate_dag 第 %d 次语义校验失败：%s", attempt, errs)

    raise PlanInvalid(last_errors)
