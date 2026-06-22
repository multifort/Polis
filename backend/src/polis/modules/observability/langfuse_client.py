"""Langfuse 只读查询封装（design 06 §3）：按 trace(=task_id) 拉 LLM 调用明细。

供 Polis 自建观测页下钻 LLM 调用级数据（prompt/输出/token/成本），不暴露 Langfuse UI。
连本地 langfuse 用 trust_env=False，绕过本机代理直连；不可达/无数据时静默返回空（best-effort）。
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from polis.config import get_settings

logger = logging.getLogger(__name__)


def _trim(v: Any, limit: int = 500) -> str:
    s = v if isinstance(v, str) else str(v)
    return s if len(s) <= limit else s[:limit] + "…"


def _num(*vals: Any) -> float | None:
    """取第一个可转 float 的非空值（兼容 langfuse 多种字段命名）。"""
    for v in vals:
        if v is None:
            continue
        try:
            return float(v)
        except (TypeError, ValueError):
            continue
    return None


def _int(*vals: Any) -> int | None:
    n = _num(*vals)
    return int(n) if n is not None else None


async def fetch_generations(trace_id: str) -> list[dict[str, Any]]:
    """拉某 trace 的 GENERATION 观测（每次 LLM 调用）。

    返回 [{name,model,input,output,input_tokens,output_tokens,total_tokens,cost}]。
    cost 透传 langfuse calculatedTotalCost（USD 数值）；token 取 usage 的 input/output/total。
    """
    s = get_settings()
    if not s.langfuse_enabled or not s.langfuse_public_key:
        return []
    try:
        async with httpx.AsyncClient(trust_env=False, timeout=5.0) as client:
            r = await client.get(
                f"{s.langfuse_host}/api/public/traces/{trace_id}",
                auth=(s.langfuse_public_key, s.langfuse_secret_key),
            )
            if r.status_code != 200:
                return []
            observations = r.json().get("observations", [])
    except Exception:  # noqa: BLE001 - 可观测后端不可达不影响主流程
        logger.debug("langfuse fetch_generations 失败（best-effort）")
        return []

    calls: list[dict[str, Any]] = []
    for o in observations:
        if o.get("type") != "GENERATION":
            continue
        usage = o.get("usage") or {}
        calls.append(
            {
                "name": o.get("name"),
                "model": o.get("model"),
                "input": _trim(o.get("input")),
                "output": _trim(o.get("output")),
                "input_tokens": _int(usage.get("input"), usage.get("promptTokens")),
                "output_tokens": _int(usage.get("output"), usage.get("completionTokens")),
                "total_tokens": _int(usage.get("total"), usage.get("totalTokens")),
                "cost": _num(o.get("calculatedTotalCost"), o.get("totalCost")),
            }
        )
    return calls
