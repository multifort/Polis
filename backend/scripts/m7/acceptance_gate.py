"""M7 端到端验收门 harness（T8.2 + T3.7）。

驱动真实运行栈（FastAPI + Temporal worker + DeepSeek + Langfuse）跑一组采购目标，
量化 V1 验收门四项指标（03 §9）：
  - DAG 可用率：意图→产出可运行 DAG（模板命中 + 校验通过）的比例     目标 ≥ 70%
  - 路由命中率：被选 Agent 的能力覆盖节点能力需求的比例（自动代理）   目标 ≥ 75%
  - 人审通过率：终产出经 Evaluator(LLM-judge) 一次通过的比例（代理）   目标 ≥ 50%
  - 成本/时延：实际成本(元)≤计划预算，时延在阈值内

两种模式：
  --dry  仅出图（确定性、零 LLM、秒级）→ 得 DAG 可用率 + 路由命中率
  --full 出图→批准→运行→观测→评测（真实 LLM，慢/有成本）→ 全四项指标

用法（需先起后端 + worker + temporal，见续接指南 §3）：
  uv run python scripts/m7/acceptance_gate.py --dry
  uv run python scripts/m7/acceptance_gate.py --full --limit 3
  uv run python scripts/m7/acceptance_gate.py --dry --goals-file scripts/m7/goals_b_stability.json
  可选：--org-id <已有花名册的公司>（缺省则用预设新建一家验收门公司）
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

import httpx

DEFAULT_BASE = "http://127.0.0.1:8000"
DEFAULT_EMAIL = "demo_li@polis.dev"
DEFAULT_PASSWORD = "secret123"
DEFAULT_REQUEST_TIMEOUT = 120.0
GOALS_PATH = Path(__file__).with_name("goals.json")
TERMINAL_RUN_STATUSES = {"done", "failed", "needs_review"}


class Gate:
    def __init__(self, base: str, email: str, password: str, request_timeout: float) -> None:
        self.base = base.rstrip("/")
        self.email = email
        self.password = password
        self.client = httpx.Client(base_url=self.base, trust_env=False, timeout=request_timeout)
        self.token = self._login(email, password)
        self.org_id: str = ""

    def relogin(self) -> None:
        """access JWT 短时（~15min）；长跑前每个目标前刷新，避免中途 401。"""
        self.token = self._login(self.email, self.password)

    def _h(self) -> dict[str, str]:
        h = {"Authorization": f"Bearer {self.token}"}
        if self.org_id:
            h["X-Org-Id"] = self.org_id
        return h

    def _login(self, email: str, password: str) -> str:
        r = self.client.post("/api/auth/login", json={"email": email, "password": password})
        r.raise_for_status()
        return str(r.json()["access_token"])

    def ensure_org(self, org_id: str | None) -> str:
        if org_id:
            self.org_id = org_id
            return org_id
        # 用预设新建一家「采购分析公司」作为隔离的验收门环境
        name = f"M7验收门-{int(time.time())}"
        r = self.client.post(
            "/api/provision",
            headers={"Authorization": f"Bearer {self.token}"},
            json={"name": name, "keyword": "采购"},
        )
        r.raise_for_status()
        self.org_id = str(r.json()["org"]["id"])
        print(f"  · 新建验收门公司：{name}  org_id={self.org_id}", flush=True)
        return self.org_id

    def agents(self) -> dict[str, list[str]]:
        r = self.client.get("/api/orgs/current/agents", headers=self._h())
        r.raise_for_status()
        return {a["name"]: (a.get("capabilities") or []) for a in r.json()}

    def create_plan(self, goal: str) -> tuple[int, dict[str, Any]]:
        r = self.client.post("/api/plans", headers=self._h(), json={"goal": goal})
        body: dict[str, Any] = r.json() if r.content else {}
        return r.status_code, body

    def approve(self, plan_id: str) -> int:
        r = self.client.post(f"/api/plans/{plan_id}/approve", headers=self._h())
        return r.status_code

    def run(self, plan_id: str) -> dict[str, Any]:
        r = self.client.get(f"/api/plans/{plan_id}/run", headers=self._h())
        return {"_status": r.status_code, **(r.json() if r.content else {})}

    def observability(self, plan_id: str) -> dict[str, Any]:
        r = self.client.get(f"/api/plans/{plan_id}/observability", headers=self._h())
        return {"_status": r.status_code, **(r.json() if r.content else {})}

    def eval_output(self, output: str, acceptance: str | None) -> dict[str, Any]:
        r = self.client.post(
            "/api/eval/run",
            headers=self._h(),
            json={"output": output, "acceptance_criteria": acceptance},
        )
        r.raise_for_status()
        return dict(r.json())


def routing_hits(plan: dict[str, Any], agent_caps: dict[str, list[str]]) -> tuple[int, int]:
    """路由命中代理：每个 agent 节点，被选 Agent 能力须覆盖该节点能力需求。返回 (命中, 总)。"""
    nodes = plan.get("dag", {}).get("nodes", [])
    routing = plan.get("routing", {})
    hit = total = 0
    for n in nodes:
        if n.get("type") != "agent" or not n.get("required_capabilities"):
            continue
        total += 1
        picked = routing.get(n["id"])
        if picked and set(n["required_capabilities"]) <= set(agent_caps.get(picked, [])):
            hit += 1
    return hit, total


def poll_until_terminal(gate: Gate, plan_id: str, timeout: float) -> str:
    deadline = time.time() + timeout
    last = "unknown"
    while time.time() < deadline:
        st = gate.run(plan_id)
        last = str(st.get("status", "unknown"))
        if last in TERMINAL_RUN_STATUSES:
            return last
        time.sleep(5)
    return last


def final_output(obs: dict[str, Any]) -> str:
    """取终产出文本：优先 report.generation 节点，否则最后一个有 summary 的节点。"""
    nodes = obs.get("nodes", [])
    for n in reversed(nodes):
        if n.get("summary"):
            return str(n["summary"])
    return ""


def run_gate(args: argparse.Namespace) -> dict[str, Any]:
    goals_path = Path(args.goals_file)
    data = json.loads(goals_path.read_text(encoding="utf-8"))
    goals = data["goals"][: args.limit] if args.limit else data["goals"]

    gate = Gate(args.base, args.email, args.password, args.request_timeout)
    gate.ensure_org(args.org_id)
    caps = gate.agents()
    print(f"  · 花名册能力：{ {k: v for k, v in caps.items()} }\n", flush=True)

    rows: list[dict[str, Any]] = []
    dag_ok = route_hit = route_total = 0
    approved = done_runs = eval_pass = within_budget = needs_review_runs = failed_runs = 0
    costs: list[float] = []
    durs: list[float] = []

    for i, g in enumerate(goals, 1):
        gate.relogin()  # 刷新短时 access JWT，避免长跑中途过期
        goal = g["goal"]
        row: dict[str, Any] = {"goal": goal}
        try:
            code, plan = gate.create_plan(goal)
        except httpx.HTTPError as exc:
            row["dag_ok"] = False
            row["route"] = "-"
            row["error"] = f"{type(exc).__name__}: {exc}"
            rows.append(row)
            print(f"[{i}/{len(goals)}] {json.dumps(row, ensure_ascii=False)}", flush=True)
            continue
        row["dag_ok"] = code == 201
        if code == 201:
            dag_ok += 1
            h, t = routing_hits(plan, caps)
            route_hit += h
            route_total += t
            row["route"] = f"{h}/{t}"
            row["template"] = plan.get("template")
        else:
            row["route"] = "-"
            row["error"] = plan.get("detail")

        if args.full and code == 201:
            plan_id = plan["id"]
            budget_yuan = (plan.get("dag", {}).get("budget_cents") or 0) / 100
            ac = gate.approve(plan_id)
            if 200 <= ac < 300:
                approved += 1
                status = poll_until_terminal(gate, plan_id, args.timeout)
                row["run"] = status
                if status == "done":
                    done_runs += 1
                elif status == "needs_review":
                    needs_review_runs += 1
                elif status == "failed":
                    failed_runs += 1
                obs = gate.observability(plan_id)
                cost = float(obs.get("totals", {}).get("cost") or 0)
                dur = obs.get("duration_seconds")
                costs.append(cost)
                if dur is not None:
                    durs.append(float(dur))
                row["cost"] = round(cost, 4)
                row["dur_s"] = dur
                if status == "done":
                    out = final_output(obs)
                    ev = gate.eval_output(out, g.get("acceptance"))
                    row["judge"] = round(float(ev.get("judge_score", 0)), 2)
                    row["pass"] = bool(ev.get("passed"))
                    if ev.get("passed"):
                        eval_pass += 1
                    in_budget = (budget_yuan <= 0 or cost <= budget_yuan) and (
                        dur is None or float(dur) <= args.latency_budget
                    )
                    if in_budget:
                        within_budget += 1
                    row["in_budget"] = in_budget
            else:
                row["run"] = f"approve={ac}（编排未就绪？）"
        rows.append(row)
        print(f"[{i}/{len(goals)}] {json.dumps(row, ensure_ascii=False)}", flush=True)

    n = len(goals)
    metrics = {
        "goals": n,
        "goals_file": str(goals_path),
        "dag_available_rate": round(dag_ok / n, 3) if n else 0,
        "routing_hit_rate": round(route_hit / route_total, 3) if route_total else None,
        "human_pass_rate": round(eval_pass / done_runs, 3) if done_runs else None,
        "ran": done_runs,
        "approved_runs": approved,
        "task_completion_rate": round(done_runs / approved, 3) if approved else None,
        "needs_review_runs": needs_review_runs,
        "failed_runs": failed_runs,
        "avg_cost_yuan": round(sum(costs) / len(costs), 4) if costs else None,
        "avg_duration_s": round(sum(durs) / len(durs), 1) if durs else None,
        "within_budget_rate": round(within_budget / done_runs, 3) if done_runs else None,
    }
    return {"mode": "full" if args.full else "dry", "metrics": metrics, "rows": rows}


def verdict(m: dict[str, Any]) -> None:
    print("\n================ V1 验收门 ================", flush=True)
    gates = [
        ("DAG 可用率", m["dag_available_rate"], 0.70),
        ("路由命中率", m["routing_hit_rate"], 0.75),
        ("人审通过率", m["human_pass_rate"], 0.50),
    ]
    for name, val, thr in gates:
        if val is None:
            print(f"  {name:<8} : —（未跑/不适用）  门槛 ≥ {thr:.0%}", flush=True)
        else:
            mark = "✅" if val >= thr else "❌"
            print(f"  {name:<8} : {val:.1%}  门槛 ≥ {thr:.0%}  {mark}", flush=True)
    if m.get("avg_cost_yuan") is not None:
        within_budget = (
            f"{m['within_budget_rate']:.0%}" if m.get("within_budget_rate") is not None else "—"
        )
        print(
            f"  成本/时延 : 均成本 ¥{m['avg_cost_yuan']} · 均时延 {m['avg_duration_s']}s · "
            f"预算内 {within_budget}",
            flush=True,
        )
    if m.get("task_completion_rate") is not None:
        mark = "✅" if m["task_completion_rate"] >= 0.90 else "❌"
        print(
            f"  B任务完成 : {m['task_completion_rate']:.1%}  门槛 ≥ 90%  {mark} "
            f"(approved={m['approved_runs']}, done={m['ran']}, "
            f"needs_review={m['needs_review_runs']}, failed={m['failed_runs']})",
            flush=True,
        )
    print("==========================================", flush=True)


def main() -> None:
    p = argparse.ArgumentParser(description="M7 端到端验收门 harness")
    p.add_argument("--base", default=DEFAULT_BASE)
    p.add_argument("--email", default=DEFAULT_EMAIL)
    p.add_argument("--password", default=DEFAULT_PASSWORD)
    p.add_argument("--org-id", default=None, help="已有花名册的公司；缺省则用预设新建")
    p.add_argument("--full", action="store_true", help="出图→运行→评测（真实 LLM）")
    p.add_argument("--dry", action="store_true", help="仅出图（默认；零 LLM）")
    p.add_argument("--goals-file", default=str(GOALS_PATH), help="目标集 JSON 文件路径")
    p.add_argument("--limit", type=int, default=0, help="只跑前 N 个目标（0=全部）")
    p.add_argument(
        "--request-timeout",
        type=float,
        default=DEFAULT_REQUEST_TIMEOUT,
        help="单个 HTTP 请求超时(s)，生成路径可能超过 30s",
    )
    p.add_argument("--timeout", type=float, default=300.0, help="单任务运行轮询超时(s)")
    p.add_argument("--latency-budget", type=float, default=600.0, help="单任务时延预算(s)")
    p.add_argument("--out", default=None, help="把报告 JSON 写到文件")
    args = p.parse_args()

    report = run_gate(args)
    verdict(report["metrics"])
    if args.out:
        Path(args.out).write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"\n报告已写入 {args.out}", flush=True)


if __name__ == "__main__":
    main()
