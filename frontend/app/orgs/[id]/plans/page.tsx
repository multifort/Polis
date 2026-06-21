"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import {
  api,
  getAccess,
  type ApiError,
  type Observability,
  type PlanNode,
  type PlanResult,
  type RunStatus,
} from "@/lib/api";

// 按依赖把节点分层（拓扑层级）：无依赖在第 0 层，其余取所有前驱层级 +1。
function layerize(nodes: PlanNode[]): PlanNode[][] {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const level = new Map<string, number>();
  const visit = (id: string, seen: Set<string>): number => {
    if (level.has(id)) return level.get(id)!;
    if (seen.has(id)) return 0; // 环（理论上已被后端 validate 拦截）
    seen.add(id);
    const node = byId.get(id);
    const deps = node?.deps ?? [];
    const lv = deps.length === 0 ? 0 : Math.max(...deps.map((d) => visit(d, seen))) + 1;
    level.set(id, lv);
    return lv;
  };
  nodes.forEach((n) => visit(n.id, new Set()));
  const maxLv = Math.max(0, ...[...level.values()]);
  const layers: PlanNode[][] = Array.from({ length: maxLv + 1 }, () => []);
  nodes.forEach((n) => layers[level.get(n.id) ?? 0].push(n));
  return layers;
}

const STATUS_LABEL: Record<string, string> = {
  pending: "待执行",
  running: "执行中",
  done: "已完成",
  waiting_human: "待人审",
  failed: "失败",
};

const POLL_MS = 1500;

export default function PlansPage() {
  const router = useRouter();
  const params = useParams<{ id: string }>();
  const orgId = params.id;

  const [goal, setGoal] = useState("");
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState("");
  const [plan, setPlan] = useState<PlanResult | null>(null);

  const [run, setRun] = useState<RunStatus | null>(null);
  const [approving, setApproving] = useState(false);
  const [notice, setNotice] = useState(""); // 503 等降级提示
  const [obs, setObs] = useState<Observability | null>(null);
  const [obsLoading, setObsLoading] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (!getAccess()) router.replace("/");
  }, [router]);

  const stopPoll = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  useEffect(() => () => stopPoll(), [stopPoll]);

  async function onCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!goal.trim()) return;
    setCreating(true);
    setError("");
    setNotice("");
    setRun(null);
    stopPoll();
    setPlan(null);
    try {
      setPlan(await api.createPlan(orgId, goal.trim()));
    } catch (err) {
      setError(err instanceof Error ? err.message : "出图失败");
    } finally {
      setCreating(false);
    }
  }

  const poll = useCallback(async () => {
    if (!plan) return;
    try {
      const r = await api.planRun(orgId, plan.id);
      setRun(r);
      setNotice("");
      if (r.status === "done" || r.status === "failed") stopPoll();
    } catch (err) {
      const status = (err as ApiError).status;
      if (status === 503) setNotice("编排服务未就绪，稍后自动重试…");
      else {
        setNotice(err instanceof Error ? err.message : "查询运行状态失败");
        stopPoll();
      }
    }
  }, [orgId, plan, stopPoll]);

  async function onApprove() {
    if (!plan) return;
    setApproving(true);
    setNotice("");
    try {
      await api.approvePlan(orgId, plan.id);
      setPlan({ ...plan, status: "running" });
      await poll();
      stopPoll();
      pollRef.current = setInterval(poll, POLL_MS);
    } catch (err) {
      const status = (err as ApiError).status;
      setNotice(
        status === 503
          ? "编排服务未就绪，暂时无法运行（DAG 预览不受影响）"
          : err instanceof Error
            ? err.message
            : "启动失败",
      );
    } finally {
      setApproving(false);
    }
  }

  async function onSignal(nodeId: string) {
    if (!plan) return;
    try {
      await api.signalNode(orgId, plan.id, nodeId);
      await poll();
    } catch (err) {
      setNotice(err instanceof Error ? err.message : "审批失败");
    }
  }

  async function loadObs() {
    if (!plan) return;
    setObsLoading(true);
    setNotice("");
    try {
      setObs(await api.planObservability(orgId, plan.id));
    } catch (err) {
      const status = (err as ApiError).status;
      setNotice(status === 404 ? "该计划尚未启动，暂无观测数据" : "加载观测失败");
    } finally {
      setObsLoading(false);
    }
  }

  const runById = new Map((run?.nodes ?? []).map((n) => [n.id, n.status]));
  const layers = plan ? layerize(plan.dag.nodes) : [];

  return (
    <>
      <div className="topbar">
        <div className="brand">
          <div className="logo">A</div>
          <span className="brand-name">Polis</span>
        </div>
        <Link className="back" href={`/orgs/${orgId}`}>
          ← 返回公司
        </Link>
      </div>

      <div className="container">
        <div className="page-head">
          <div>
            <h1 className="page-title">任务 / 计划</h1>
            <p className="muted">输入目标，模板优先出图（DAG），批准后交由编排运行。</p>
          </div>
        </div>

        <form className="plan-bar" onSubmit={onCreate}>
          <input
            value={goal}
            onChange={(e) => setGoal(e.target.value)}
            placeholder="例如：分析供应商交付"
          />
          <button className="btn-primary" type="submit" disabled={creating}>
            {creating ? "出图中…" : "出图"}
          </button>
        </form>

        {error && <p className="error" style={{ marginTop: 14 }}>{error}</p>}
        {notice && <p className="notice" style={{ marginTop: 14 }}>{notice}</p>}

        {plan && (
          <>
            <div className="plan-meta">
              <span className="role-chip">模板 {plan.template}</span>
              <span className="role-chip">预估 {(plan.estimated_cost_cents / 100).toFixed(2)} 元</span>
              <span className="role-chip">{plan.dag.nodes.length} 个节点</span>
              <span className={`pill ${run ? run.status : "active"}`}>
                {run ? STATUS_LABEL[run.status] ?? run.status : "校验通过"}
              </span>
              {(plan.status === "draft" || plan.status === "approved") && !run && (
                <button
                  className="btn-mini"
                  onClick={onApprove}
                  disabled={approving}
                  style={{ marginLeft: "auto" }}
                >
                  {approving ? "启动中…" : "批准并运行"}
                </button>
              )}
            </div>

            {layers.map((layer, i) => (
              <div className="dag-layer" key={i} data-layer={`第 ${i + 1} 层`}>
                {layer.map((n) => {
                  const rStatus = runById.get(n.id);
                  const routedAgent = plan.routing[n.id];
                  return (
                    <div className={`dag-node ${n.dangerous ? "dangerous" : ""}`} key={n.id}>
                      <div className="nid">
                        <span>{n.id}</span>
                        {rStatus ? (
                          <span className={`pill ${rStatus}`}>
                            {STATUS_LABEL[rStatus] ?? rStatus}
                          </span>
                        ) : (
                          <span className="ntype">{n.type}</span>
                        )}
                      </div>
                      {n.required_capabilities.length > 0 && (
                        <div className="ncaps">
                          {n.required_capabilities.map((c) => (
                            <span className="ncap" key={c}>{c}</span>
                          ))}
                        </div>
                      )}
                      {n.type === "agent" && (
                        <div className="nroute">
                          路由 →{" "}
                          {routedAgent ? (
                            <strong>{routedAgent}</strong>
                          ) : (
                            <span className="none">无可用 Agent</span>
                          )}
                        </div>
                      )}
                      {n.deps.length > 0 && <div className="ntype">依赖：{n.deps.join("、")}</div>}
                      {rStatus === "waiting_human" && (
                        <div className="nact">
                          <button className="btn-mini" onClick={() => onSignal(n.id)}>
                            通过
                          </button>
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            ))}

            {/* 运行观测（H-3）：任务级聚合 — 模型/节点产出/LLM 调用明细 */}
            {run && (
              <>
                <div className="section-title" style={{ display: "flex", gap: 10, alignItems: "center" }}>
                  运行观测
                  <button className="btn-mini" onClick={loadObs} disabled={obsLoading}>
                    {obsLoading ? "加载中…" : obs ? "刷新" : "查看"}
                  </button>
                </div>
                {obs && (
                  <div className="obs">
                    <div className="plan-meta">
                      {obs.manifest?.models_used && (
                        <span className="role-chip">
                          模型 {Object.values(obs.manifest.models_used).join(", ")}
                        </span>
                      )}
                      <span className="role-chip">{obs.nodes.length} 个节点产出</span>
                      <span className="role-chip">{obs.llm_calls.length} 次 LLM 调用</span>
                    </div>

                    {obs.nodes.map((n) => (
                      <div className="dag-node" key={n.node_id} style={{ maxWidth: "100%" }}>
                        <div className="nid">
                          <span>{n.node_id}</span>
                          <span className={`pill ${n.status}`}>
                            {STATUS_LABEL[n.status] ?? n.status}
                          </span>
                        </div>
                        {n.summary && <div className="nroute">{n.summary}</div>}
                        {n.provenance?.agent != null && (
                          <div className="ntype">
                            Agent：{String(n.provenance.agent)}
                            {n.provenance.model != null ? ` · 模型 ${String(n.provenance.model)}` : ""}
                          </div>
                        )}
                        {n.needs_human && <span className="pill waiting_human">需人审</span>}
                      </div>
                    ))}

                    {obs.llm_calls.length > 0 && (
                      <>
                        <div className="section-title">LLM 调用明细（Langfuse）</div>
                        {obs.llm_calls.map((c, i) => (
                          <div className="dag-node" key={i} style={{ maxWidth: "100%" }}>
                            <div className="nid">
                              <span>{c.name || "generation"}</span>
                              <span className="ntype">
                                {c.model}
                                {c.total_tokens != null ? ` · ${c.total_tokens} tokens` : ""}
                              </span>
                            </div>
                            {c.output && <div className="nroute">{c.output}</div>}
                          </div>
                        ))}
                      </>
                    )}
                    {obs.llm_calls.length === 0 && (
                      <p className="hint">暂无 LLM 调用明细（Langfuse 未启用或本次无真实模型调用）。</p>
                    )}
                  </div>
                )}
              </>
            )}
          </>
        )}
      </div>
    </>
  );
}
