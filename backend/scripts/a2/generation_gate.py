"""A2 规划生成验证门（in-process）。

直接驱动 `planner.generator.generate_dag`（真实 LiteLLM/DeepSeek），在受控能力集 + 模板范例下
跑一组「模板未命中」目标，量化 A2 验收指标（design v2/01 §4.6）：

  - 生成 DAG 可用率：生成→过结构+语义双校验的比例（含 ≤1 次自修复）   目标 ≥ 70%
  - 结构合法率（一次过）：首轮即过 Pydantic+validate 的比例             目标 ≥ 80%
  - 平均尝试次数 / 平均节点数（观测项）

为什么 in-process 而非走 HTTP：A2 度量的是「生成质量」本身（可用率/一次过率/尝试数），
in-process 可精确拿到每个目标的尝试轮次，且不依赖 Temporal/审批链，隔离被测对象。

用法（需 .env 里有 DeepSeek Key；模型取 config.default_chat_model）：
  uv run python scripts/a2/generation_gate.py
  uv run python scripts/a2/generation_gate.py --limit 3
  uv run python scripts/a2/generation_gate.py --attempts 2 --exemplars-from-db
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any

from polis.config import get_settings
from polis.db.session import get_sessionmaker, init_engine
from polis.modules.model.gateway import ResolvedModel, resolve_model
from polis.modules.model.litellm_gateway import LiteLLMGateway
from polis.modules.planner.errors import PlanInvalid
from polis.modules.planner.generator import generate_dag

GOALS_PATH = Path(__file__).with_name("goals_a2.json")

# A2 验收门槛（design v2/01 §4.6）
USABLE_TARGET = 0.70
ONEPASS_TARGET = 0.80


class _AttemptCapture(logging.Handler):
    """抓 generator 的「第 N 次通过/失败」INFO 日志，按目标精确还原尝试轮次。"""

    def __init__(self) -> None:
        super().__init__(level=logging.INFO)
        self.records: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record.getMessage())

    def reset(self) -> None:
        self.records.clear()

    def passed_attempt(self) -> int | None:
        """返回「第几次通过」；未通过 → None。"""
        for msg in self.records:
            if "次通过" in msg:
                # 形如 "generate_dag 第 1 次通过（4 节点）"
                try:
                    return int(msg.split("第", 1)[1].split("次", 1)[0].strip())
                except (IndexError, ValueError):
                    return 1
        return None


async def _load_exemplars(from_db: bool) -> list[dict[str, Any]]:
    if not from_db:
        return []
    from sqlalchemy import select

    from polis.modules.planner.models import PlanTemplate

    async with get_sessionmaker()() as session:
        rows = (await session.scalars(select(PlanTemplate).limit(3))).all()
        return [r.dag_skeleton for r in rows]


async def _resolve() -> ResolvedModel:
    async with get_sessionmaker()() as session:
        return await resolve_model(session, get_settings().default_chat_model)


async def run(limit: int | None, attempts: int, exemplars_from_db: bool) -> int:
    spec = json.loads(GOALS_PATH.read_text(encoding="utf-8"))
    available: set[str] = set(spec["available_capabilities"])
    goals: list[str] = spec["goals"][: limit or len(spec["goals"])]

    init_engine()
    model = await _resolve()
    exemplars = await _load_exemplars(exemplars_from_db)
    gateway = LiteLLMGateway()

    cap = _AttemptCapture()
    gen_logger = logging.getLogger("polis.modules.planner.generator")
    gen_logger.setLevel(logging.INFO)
    gen_logger.addHandler(cap)

    print(f"A2 生成验证门：{len(goals)} 目标 · 模型={model.id} · 能力集={sorted(available)}")
    print(f"范例={'DB模板' if exemplars_from_db else '无'} · 自修复上限 N={attempts}\n")

    usable = 0
    onepass = 0
    total_attempts = 0
    total_nodes = 0
    rows: list[dict[str, Any]] = []

    for i, goal in enumerate(goals, 1):
        cap.reset()
        t0 = time.time()
        ok = False
        nodes = 0
        att: int | None = None
        err = ""
        try:
            dag = await generate_dag(gateway, model, goal, available, exemplars, attempts=attempts)
            ok = True
            nodes = len(dag.nodes)
            att = cap.passed_attempt() or 1
        except PlanInvalid as exc:
            att = None
            err = "；".join(exc.errors)[:80]
        except Exception as exc:  # noqa: BLE001 — 验证门要继续跑完
            att = None
            err = f"{type(exc).__name__}: {exc}"[:80]

        dt = time.time() - t0
        if ok:
            usable += 1
            total_nodes += nodes
            assert att is not None
            total_attempts += att
            if att == 1:
                onepass += 1
        status = f"✅ {nodes}节点/第{att}次" if ok else f"❌ {err}"
        print(f"[{i:>2}/{len(goals)}] {dt:5.1f}s  {status}  «{goal[:28]}»")
        rows.append({"goal": goal, "ok": ok, "attempt": att, "nodes": nodes, "err": err})

    n = len(goals)
    usable_rate = usable / n if n else 0.0
    # 一次过率：以「可用」为分母（结构合法率衡量生成质量，对失败项不计入分母外）
    onepass_rate = onepass / usable if usable else 0.0
    avg_attempts = total_attempts / usable if usable else 0.0
    avg_nodes = total_nodes / usable if usable else 0.0

    u_flag = "PASS" if usable_rate >= USABLE_TARGET else "FAIL"
    o_flag = "PASS" if onepass_rate >= ONEPASS_TARGET else "FAIL"
    print("\n── 汇总 ──")
    print(
        f"生成 DAG 可用率   {usable}/{n} = {usable_rate:.0%}   目标≥{USABLE_TARGET:.0%}  {u_flag}"
    )
    print(
        f"结构合法率(一次过) {onepass}/{usable} = {onepass_rate:.0%}   "
        f"目标≥{ONEPASS_TARGET:.0%}  {o_flag}"
    )
    print(f"平均尝试次数      {avg_attempts:.2f}")
    print(f"平均节点数        {avg_nodes:.1f}")

    gate_pass = usable_rate >= USABLE_TARGET and onepass_rate >= ONEPASS_TARGET
    verdict = "✅ PASS" if gate_pass else "❌ FAIL（回炉调 prompt/范例/能力词表，勿加模块）"
    print(f"\n验证门：{verdict}")
    return 0 if gate_pass else 1


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="只跑前 N 个目标")
    ap.add_argument("--attempts", type=int, default=2, help="自修复上限 N（默认 2）")
    ap.add_argument(
        "--exemplars-from-db", action="store_true", help="从 plan_template 取范例骨架接地"
    )
    args = ap.parse_args()
    raise SystemExit(asyncio.run(run(args.limit, args.attempts, args.exemplars_from_db)))


if __name__ == "__main__":
    main()
