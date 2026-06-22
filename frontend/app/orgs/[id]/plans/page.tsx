"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  api,
  getAccess,
  type Agent,
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
  idle: "待确认执行", // 运行前（已校验、待批准）
  pending: "待执行",
  running: "执行中",
  done: "已完成",
  waiting_human: "待人审",
  failed: "失败",
};

// ── SVG 流程图布局 ──────────────────────────────────────────────
const NODE_W = 252;
const NODE_H = 142;
const H_GAP = 28;
const V_GAP = 58;
const PAD = 14;

type Pos = { x: number; y: number };
function layoutFlow(layers: PlanNode[][]) {
  const widths = layers.map((l) => l.length * NODE_W + Math.max(0, l.length - 1) * H_GAP);
  const maxW = Math.max(NODE_W, ...widths);
  const pos = new Map<string, Pos>();
  layers.forEach((layer, li) => {
    let x = PAD + (maxW - widths[li]) / 2;
    const y = PAD + li * (NODE_H + V_GAP);
    layer.forEach((n) => {
      pos.set(n.id, { x, y });
      x += NODE_W + H_GAP;
    });
  });
  return {
    pos,
    width: maxW + PAD * 2,
    height: PAD * 2 + layers.length * NODE_H + Math.max(0, layers.length - 1) * V_GAP,
  };
}

const POLL_MS = 1500;
// 成本单位为「元」（后端按 model_catalog 目录价 token×单价 实算）。
const fmtCost = (yuan: number | null | undefined) =>
  yuan == null ? "—" : `¥${yuan.toFixed(4)}`;
const fmtNum = (n: number | null | undefined) => (n == null ? "—" : n.toLocaleString());

const fmtTime = (iso: string | null | undefined) => {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? ""
    : d.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
};
const fmtDuration = (sec: number | null | undefined) => {
  if (sec == null) return "—";
  const s = Math.max(0, Math.round(sec));
  const hh = String(Math.floor(s / 3600)).padStart(2, "0");
  const mm = String(Math.floor((s % 3600) / 60)).padStart(2, "0");
  const ss = String(s % 60).padStart(2, "0");
  return `${hh}:${mm}:${ss}`;
};

// 节点能力标签：优先展示技能/能力名（如 procurement.rfq），回退 executor/type。
const capLabel = (n: PlanNode): string =>
  n.required_capabilities[0] ?? n.executor ?? n.type;

// Agent 职责描述：去掉开头的「你」（promptSkeleton 多以"你负责…"开头）。
const cleanDesc = (s: string | null | undefined): string =>
  (s ?? "").replace(/^你/, "").trim();

// 节点种类 → 图标（按能力/执行体关键字归类，决定卡片左侧图标）。
function nodeKind(n: PlanNode): string {
  const c = `${n.required_capabilities.join(" ")} ${n.executor} ${n.type}`.toLowerCase();
  if (c.includes("rfq") || c.includes("询价")) return "rfq";
  if (c.includes("supplier")) return "supplier";
  if (c.includes("spend") || c.includes("analysis")) return "analysis";
  if (c.includes("report") || c.includes("generation")) return "report";
  if (n.type === "human") return "human";
  return "agent";
}

const ICON_PATHS: Record<string, string> = {
  // 文档（询价/RFQ）
  rfq: "M6 2h7l5 5v15a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V3a1 1 0 0 1 1-1Zm7 1.5V8h4.5M8 12h8M8 16h8M8 8h3",
  // 团队（供应商分析）
  supplier: "M9 11a3 3 0 1 0 0-6 3 3 0 0 0 0 6Zm7 0a3 3 0 1 0 0-6 3 3 0 0 0 0 6ZM3 20a6 6 0 0 1 12 0M14 20a6 6 0 0 1 7-5.2",
  // 柱状图（支出分析）
  analysis: "M5 21V10M12 21V4M19 21v-7M3 21h18",
  // 报告（清单）
  report: "M8 4h8a1 1 0 0 1 1 1v15l-2.5-1.5L12 20l-2.5-1.5L7 20V5a1 1 0 0 1 1-1Zm1.5 4h5M9.5 11h5",
  human: "M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8Zm-7 9a7 7 0 0 1 14 0",
  agent: "M6 2h7l5 5v15a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V3a1 1 0 0 1 1-1Zm7 1.5V8h4.5",
};

function NodeIcon({ kind, className = "" }: { kind: string; className?: string }) {
  return (
    <span className={`node-ico ${className}`}>
      <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
        <path d={ICON_PATHS[kind] ?? ICON_PATHS.agent} />
      </svg>
    </span>
  );
}

export default function PlansPage() {
  const router = useRouter();
  const params = useParams<{ id: string }>();
  const orgId = params.id;

  const [goal, setGoal] = useState("");
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState("");
  const [plan, setPlan] = useState<PlanResult | null>(null);
  const [view, setView] = useState<"graph" | "list">("graph");

  const [run, setRun] = useState<RunStatus | null>(null);
  const [approving, setApproving] = useState(false);
  const [notice, setNotice] = useState(""); // 503 等降级提示
  const [obs, setObs] = useState<Observability | null>(null);
  const [obsLoading, setObsLoading] = useState(false);
  const [selectedNode, setSelectedNode] = useState<string | null>(null);
  const [showLog, setShowLog] = useState(false);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [agentModal, setAgentModal] = useState<Agent | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (!getAccess()) router.replace("/");
  }, [router]);

  // 拉当前公司花名册（Agent 名→详情），供节点卡描述与「Agent 详情」模态。
  useEffect(() => {
    api
      .agents(orgId)
      .then(setAgents)
      .catch(() => setAgents([]));
  }, [orgId]);

  // 左侧 DAG 点击节点 → 右侧观测对应卡片展开并滚动到视野（联动）。
  useEffect(() => {
    if (!selectedNode) return;
    const el = document.getElementById(`obs-node-${selectedNode}`);
    if (el) el.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [selectedNode, obs]);

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
    setObs(null);
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
      if (r.status === "done" || r.status === "failed") {
        stopPoll();
        loadObs(); // 终态自动拉一次观测
      }
    } catch (err) {
      const status = (err as ApiError).status;
      if (status === 503) setNotice("编排服务未就绪，稍后自动重试…");
      else {
        setNotice(err instanceof Error ? err.message : "查询运行状态失败");
        stopPoll();
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
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
    try {
      setObs(await api.planObservability(orgId, plan.id));
    } catch (err) {
      const status = (err as ApiError).status;
      if (status !== 404) setNotice("加载观测失败");
    } finally {
      setObsLoading(false);
    }
  }

  // 点击 DAG 节点：选中该节点（右侧展开联动）；若观测未加载则顺手拉一次。
  function selectNode(id: string) {
    setSelectedNode(id);
    if (run && !obs && !obsLoading) loadObs();
  }

  const runById = new Map((run?.nodes ?? []).map((n) => [n.id, n.status]));
  const layers = plan ? layerize(plan.dag.nodes) : [];
  const flowStatus = (id: string): string | undefined =>
    runById.get(id) ?? (run ? "pending" : undefined);
  const nodeMetaById = new Map((plan?.dag.nodes ?? []).map((n) => [n.id, n]));
  const obsTimeById = new Map((obs?.nodes ?? []).map((n) => [n.node_id, n.created_at]));
  const timeOf = (id: string): string => fmtTime(obsTimeById.get(id) ?? null);
  const agentByName = new Map(agents.map((a) => [a.name, a]));
  const agentOf = (id: string): Agent | undefined => {
    const name = plan?.routing[id];
    return name ? agentByName.get(name) : undefined;
  };
  const openAgent = (name: string | null | undefined) => {
    if (name) setAgentModal(agentByName.get(name) ?? null);
  };

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

      <div className="container wide">
        <div className="page-head">
          <div className="title-row">
            <div className="title-ico">🗂</div>
            <div>
              <h1 className="page-title big">任务 / 计划</h1>
              <p className="muted">输入目标，模板优先出图（DAG），批准后交由编排运行。</p>
            </div>
          </div>
        </div>

        <form className="plan-bar" onSubmit={onCreate}>
          <input
            value={goal}
            onChange={(e) => setGoal(e.target.value)}
            placeholder="例如：分析供应商交付"
          />
          <button className="btn-primary" type="submit" disabled={creating}>
            {creating ? "出图中…" : "✦ 出图"}
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
            </div>

            <div className="ops-grid">
              {/* ── 左：执行计划 DAG ── */}
              <section className="panel">
                <div className="panel-head">
                  <h2>执行计划（DAG）</h2>
                  <div className="head-actions">
                    <div className="seg">
                      <button
                        className={view === "graph" ? "on" : ""}
                        onClick={() => setView("graph")}
                        title="流程图"
                      >
                        ⛓ 图
                      </button>
                      <button
                        className={view === "list" ? "on" : ""}
                        onClick={() => setView("list")}
                        title="列表"
                      >
                        ☰ 表
                      </button>
                    </div>
                    {(plan.status === "draft" || plan.status === "approved") && !run && (
                      <button className="btn-run" onClick={onApprove} disabled={approving}>
                        {approving ? "启动中…" : "✓ 批准并运行"}
                      </button>
                    )}
                  </div>
                </div>

                {view === "graph" ? (
                  <FlowGraph
                    layers={layers}
                    plan={plan}
                    statusOf={flowStatus}
                    timeOf={timeOf}
                    agentOf={agentOf}
                    onAgentClick={openAgent}
                    selectedId={selectedNode}
                    onSelect={selectNode}
                    onSignal={onSignal}
                  />
                ) : (
                  <ListView
                    layers={layers}
                    plan={plan}
                    statusOf={flowStatus}
                    timeOf={timeOf}
                    agentOf={agentOf}
                    onAgentClick={openAgent}
                    selectedId={selectedNode}
                    onSelect={selectNode}
                    onSignal={onSignal}
                  />
                )}

                {/* 计划级统计卡 */}
                <div className="stat-row">
                  {obs ? (
                    <Stat ico="¥" label="实际费用" value={fmtCost(obs.totals.cost)} />
                  ) : (
                    <Stat ico="¥" label="预估费用" value={`${(plan.estimated_cost_cents / 100).toFixed(2)} 元`} />
                  )}
                  <Stat ico="◇" label="节点数量" value={String(plan.dag.nodes.length)} />
                  <Stat ico="⏱" label="总耗时" value={obs ? fmtDuration(obs.duration_seconds) : "—"} />
                  <Stat
                    ico="✓"
                    label="状态"
                    value={run ? STATUS_LABEL[run.status] ?? run.status : "未运行"}
                  />
                </div>
              </section>

              {/* ── 右：运行观测 ── */}
              <aside className="panel obs-panel">
                <div className="panel-head">
                  <h2>运行观测</h2>
                  <button className="icon-btn" onClick={loadObs} disabled={obsLoading || !run}>
                    {obsLoading ? "加载中…" : "↻ 刷新"}
                  </button>
                </div>

                {!run && <p className="hint">批准并运行后，这里展示节点产出与 Token / 成本统计。</p>}

                {run && !obs && (
                  <p className="hint">
                    {obsLoading ? "正在加载观测数据…" : "运行中，点「刷新」查看产出与用量。"}
                  </p>
                )}

                {obs && (
                  <>
                    <div className="obs-chips">
                      {obs.manifest?.models_used && (
                        <span className="role-chip">
                          模型 {Object.values(obs.manifest.models_used).join(", ")}
                        </span>
                      )}
                      <span className="role-chip">{obs.nodes.length} 个节点产出</span>
                      <span className="role-chip">{obs.totals.calls} 次 LLM 调用</span>
                    </div>

                    {/* 节点产出：折叠卡 + markdown 渲染（图标 / 时间 / 折叠箭头） */}
                    <div className="obs-nodes">
                      {obs.nodes.map((n, i) => {
                        const meta = nodeMetaById.get(n.node_id);
                        const kind = meta ? nodeKind(meta) : "agent";
                        const agent = n.provenance?.agent;
                        const open = selectedNode ? selectedNode === n.node_id : i === 0;
                        return (
                          <details
                            id={`obs-node-${n.node_id}`}
                            className={`obs-node ${n.status} ${selectedNode === n.node_id ? "sel" : ""}`}
                            key={n.node_id}
                            open={open}
                          >
                            <summary
                              onClick={(e) => {
                                e.preventDefault();
                                setSelectedNode(selectedNode === n.node_id ? null : n.node_id);
                              }}
                            >
                              <NodeIcon kind={kind} className="sm" />
                              <span className="oid">{n.node_id}</span>
                              {agent != null && <span className="oagent">{String(agent)}</span>}
                              <span className={`pill ${n.status}`}>
                                {STATUS_LABEL[n.status] ?? n.status}
                              </span>
                              {n.needs_human && <span className="pill waiting_human">需人审</span>}
                              {timeOf(n.node_id) && (
                                <span className="otime">⏱ {timeOf(n.node_id)}</span>
                              )}
                            </summary>
                            <div className="md">
                              {n.summary ? (
                                <ReactMarkdown remarkPlugins={[remarkGfm]}>{n.summary}</ReactMarkdown>
                              ) : (
                                <p className="hint">（无产出文本）</p>
                              )}
                            </div>
                          </details>
                        );
                      })}
                    </div>

                    {obs.nodes.length === 0 && (
                      <p className="hint">该运行暂无节点产出记录。</p>
                    )}

                    {/* 用量统计（token/成本，对标 Langfuse Dashboard）— 默认收纳折叠 */}
                    <details className="usage-fold">
                      <summary>
                        <span>用量统计</span>
                        <span className="usage-sum">
                          {fmtNum(obs.totals.total_tokens)} tokens · {obs.totals.calls} 次调用 ·{" "}
                          {fmtCost(obs.totals.cost)}
                        </span>
                      </summary>
                      <div className="usage-cards">
                        <UsageCard label="总 Token" value={fmtNum(obs.totals.total_tokens)} />
                        <UsageCard label="总成本" value={fmtCost(obs.totals.cost)} />
                        <UsageCard label="LLM 调用" value={`${obs.totals.calls} 次`} />
                      </div>
                      {obs.by_model.length > 0 ? (
                        <table className="usage-tbl">
                          <thead>
                            <tr>
                              <th>模型</th>
                              <th>调用</th>
                              <th>输入</th>
                              <th>输出</th>
                              <th>合计</th>
                              <th>成本</th>
                            </tr>
                          </thead>
                          <tbody>
                            {obs.by_model.map((m) => (
                              <tr key={m.model}>
                                <td className="m">{m.model}</td>
                                <td>{m.calls}</td>
                                <td>{fmtNum(m.input_tokens)}</td>
                                <td>{fmtNum(m.output_tokens)}</td>
                                <td>{fmtNum(m.total_tokens)}</td>
                                <td>{fmtCost(m.cost)}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      ) : (
                        <p className="hint">
                          暂无 LLM 调用用量（Langfuse 未启用或本次无真实模型调用）。
                        </p>
                      )}
                    </details>

                    <button className="full-log" onClick={() => setShowLog(true)}>
                      查看完整日志 <span className="chev">›</span>
                    </button>
                  </>
                )}
              </aside>
            </div>
          </>
        )}
      </div>

      {showLog && obs && (
        <LogModal obs={obs} nodeMetaById={nodeMetaById} onClose={() => setShowLog(false)} />
      )}

      {agentModal && <AgentModal agent={agentModal} onClose={() => setAgentModal(null)} />}
    </>
  );
}

function AgentModal({ agent, onClose }: { agent: Agent; onClose: () => void }) {
  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal agent-modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <div className="am-title">
            <span className="node-ico">
              <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
                <path d={ICON_PATHS.human} />
              </svg>
            </span>
            <div>
              <h3>{agent.name}</h3>
              {agent.role && <div className="am-role">{agent.role}</div>}
            </div>
          </div>
          <button className="modal-x" onClick={onClose}>
            ×
          </button>
        </div>

        <div className="am-row">
          <span className={`pill ${agent.status === "active" ? "done" : "pending"}`}>
            {agent.status === "active" ? "在岗" : agent.status}
          </span>
          {agent.source && <span className="am-tag">来源 {agent.source}</span>}
          {agent.current_version && <span className="am-tag">版本 {agent.current_version}</span>}
          {agent.model && <span className="am-tag">模型 {agent.model}</span>}
        </div>

        <div className="am-label">职责说明</div>
        <p className="am-desc">{cleanDesc(agent.description) || "（暂无描述）"}</p>

        {agent.capabilities && agent.capabilities.length > 0 && (
          <>
            <div className="am-label">能力清单</div>
            <div className="am-caps">
              {agent.capabilities.map((c) => (
                <span className="cap-pill" key={c}>
                  {c}
                </span>
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function LogModal({
  obs,
  nodeMetaById,
  onClose,
}: {
  obs: Observability;
  nodeMetaById: Map<string, PlanNode>;
  onClose: () => void;
}) {
  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal log-modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <h3>完整运行日志</h3>
          <button className="modal-x" onClick={onClose}>
            ×
          </button>
        </div>
        <div className="modal-desc" style={{ marginBottom: 12 }}>
          任务 {obs.task_id.slice(0, 8)} · {STATUS_LABEL[obs.status] ?? obs.status} · 总耗时{" "}
          {fmtDuration(obs.duration_seconds)} · {fmtNum(obs.totals.total_tokens)} tokens ·{" "}
          {fmtCost(obs.totals.cost)}
        </div>

        <div className="log-body">
          <div className="log-section-title">节点产出</div>
          {obs.nodes.map((n) => {
            const meta = nodeMetaById.get(n.node_id);
            return (
              <div className="log-block" key={`n-${n.node_id}`}>
                <div className="log-block-head">
                  <NodeIcon kind={meta ? nodeKind(meta) : "agent"} className="sm" />
                  <strong>{n.node_id}</strong>
                  {n.provenance?.agent != null && (
                    <span className="oagent">{String(n.provenance.agent)}</span>
                  )}
                  <span className={`pill ${n.status}`}>{STATUS_LABEL[n.status] ?? n.status}</span>
                  {fmtTime(n.created_at) && <span className="otime">⏱ {fmtTime(n.created_at)}</span>}
                </div>
                <div className="md">
                  {n.summary ? (
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>{n.summary}</ReactMarkdown>
                  ) : (
                    <p className="hint">（无产出文本）</p>
                  )}
                </div>
              </div>
            );
          })}

          <div className="log-section-title">LLM 调用明细（{obs.llm_calls.length}）</div>
          {obs.llm_calls.length === 0 && (
            <p className="hint">暂无 LLM 调用明细（Langfuse 未启用或本次无真实模型调用）。</p>
          )}
          {obs.llm_calls.map((c, i) => (
            <div className="log-block" key={`c-${i}`}>
              <div className="log-block-head">
                <strong>{c.name || `调用 ${i + 1}`}</strong>
                <span className="oagent">{c.model}</span>
                <span className="otime">
                  in {fmtNum(c.input_tokens)} · out {fmtNum(c.output_tokens)} · {fmtCost(c.cost)}
                </span>
              </div>
              {c.input && (
                <pre className="log-pre">
                  <span className="log-pre-tag">输入</span>
                  {c.input}
                </pre>
              )}
              {c.output && (
                <pre className="log-pre">
                  <span className="log-pre-tag">输出</span>
                  {c.output}
                </pre>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ── 子组件 ──────────────────────────────────────────────────────

function Stat({ ico, label, value }: { ico: string; label: string; value: string }) {
  return (
    <div className="stat">
      <div className="stat-ico">{ico}</div>
      <div>
        <div className="stat-label">{label}</div>
        <div className="stat-value">{value}</div>
      </div>
    </div>
  );
}

function UsageCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="usage-card">
      <div className="uc-value">{value}</div>
      <div className="uc-label">{label}</div>
    </div>
  );
}

function FlowGraph({
  layers,
  plan,
  statusOf,
  timeOf,
  agentOf,
  onAgentClick,
  selectedId,
  onSelect,
  onSignal,
}: {
  layers: PlanNode[][];
  plan: PlanResult;
  statusOf: (id: string) => string | undefined;
  timeOf: (id: string) => string;
  agentOf: (id: string) => Agent | undefined;
  onAgentClick: (name: string | null | undefined) => void;
  selectedId: string | null;
  onSelect: (id: string) => void;
  onSignal: (id: string) => void;
}) {
  const { pos, width, height } = layoutFlow(layers);
  const edges: { from: string; to: string }[] = [];
  layers.flat().forEach((n) => n.deps.forEach((d) => edges.push({ from: d, to: n.id })));

  return (
    <div className="flow-wrap">
      <svg viewBox={`0 0 ${width} ${height}`} className="flow-svg" style={{ width: "100%" }}>
        <defs>
          <marker id="arrow" markerWidth="10" markerHeight="10" refX="7" refY="3" orient="auto">
            <path d="M0,0 L7,3 L0,6 Z" fill="var(--color-border-strong)" />
          </marker>
        </defs>
        {edges.map((e, i) => {
          const a = pos.get(e.from);
          const b = pos.get(e.to);
          if (!a || !b) return null;
          const sx = a.x + NODE_W / 2;
          const sy = a.y + NODE_H;
          const tx = b.x + NODE_W / 2;
          const ty = b.y - 6;
          const my = (sy + ty) / 2;
          return (
            <path
              key={i}
              d={`M ${sx} ${sy} C ${sx} ${my}, ${tx} ${my}, ${tx} ${ty}`}
              fill="none"
              stroke="var(--color-border-strong)"
              strokeWidth={1.4}
              strokeDasharray="5 4"
              markerEnd="url(#arrow)"
            />
          );
        })}
        {layers.flat().map((n) => {
          const p = pos.get(n.id)!;
          const st = statusOf(n.id) ?? "idle";
          const routed = plan.routing[n.id];
          const t = timeOf(n.id);
          const agent = agentOf(n.id);
          return (
            <foreignObject key={n.id} x={p.x} y={p.y} width={NODE_W} height={NODE_H}>
              <div
                className={`flow-node ${st} ${n.dangerous ? "dangerous" : ""} ${selectedId === n.id ? "sel" : ""}`}
                onClick={() => onSelect(n.id)}
                role="button"
                tabIndex={0}
              >
                <div className="fn-top">
                  <NodeIcon kind={nodeKind(n)} className="sm" />
                  <span className="fn-id">{n.id}</span>
                  <span className="fn-exec">{capLabel(n)}</span>
                </div>
                <div className="fn-mid">
                  {n.type === "agent" ? (
                    routed ? (
                      <strong
                        className="agent-link"
                        title="查看 Agent 详情"
                        onClick={(e) => {
                          e.stopPropagation();
                          onAgentClick(routed);
                        }}
                      >
                        {routed}
                      </strong>
                    ) : (
                      <span className="fn-route">
                        <em>无可用 Agent</em>
                      </span>
                    )
                  ) : (
                    <span className="fn-route">{n.type}</span>
                  )}
                </div>
                <div className="fn-desc" title={cleanDesc(agent?.description)}>
                  {cleanDesc(agent?.description) || "—"}
                </div>
                <div className="fn-bot">
                  <span className={`pill ${st === "idle" ? "pending" : st}`}>
                    {STATUS_LABEL[st] ?? st}
                  </span>
                  {st === "waiting_human" ? (
                    <button
                      className="btn-mini"
                      onClick={(e) => {
                        e.stopPropagation();
                        onSignal(n.id);
                      }}
                    >
                      通过
                    </button>
                  ) : (
                    t && <span className="fn-time">⏱ {t}</span>
                  )}
                </div>
              </div>
            </foreignObject>
          );
        })}
      </svg>
    </div>
  );
}

function ListView({
  layers,
  plan,
  statusOf,
  timeOf,
  agentOf,
  onAgentClick,
  selectedId,
  onSelect,
  onSignal,
}: {
  layers: PlanNode[][];
  plan: PlanResult;
  statusOf: (id: string) => string | undefined;
  timeOf: (id: string) => string;
  agentOf: (id: string) => Agent | undefined;
  onAgentClick: (name: string | null | undefined) => void;
  selectedId: string | null;
  onSelect: (id: string) => void;
  onSignal: (id: string) => void;
}) {
  return (
    <div className="timeline">
      {layers.map((layer, i) => {
        const allDone = layer.every((n) => statusOf(n.id) === "done");
        const anyActive = layer.some((n) =>
          ["running", "waiting_human"].includes(statusOf(n.id) ?? ""),
        );
        const railState = allDone ? "done" : anyActive ? "active" : "idle";
        return (
          <div className="tl-layer" key={i}>
            <div className="tl-rail">
              <span className={`tl-dot ${railState}`}>{allDone ? "✓" : ""}</span>
              <span className="tl-label">第 {i + 1} 层</span>
            </div>
            <div className="tl-nodes">
              {layer.map((n) => {
                const st = statusOf(n.id) ?? "idle";
                const routed = plan.routing[n.id];
                const t = timeOf(n.id);
                const agent = agentOf(n.id);
                return (
                  <div
                    className={`dag-node2 ${st} ${n.dangerous ? "dangerous" : ""} ${selectedId === n.id ? "sel" : ""}`}
                    key={n.id}
                    onClick={() => onSelect(n.id)}
                    role="button"
                    tabIndex={0}
                  >
                    <NodeIcon kind={nodeKind(n)} />
                    <div className="dn-body">
                      <div className="dn-top">
                        <span className="dn-id">{n.id}</span>
                        <span className="cap-pill">{capLabel(n)}</span>
                      </div>
                      {n.type === "agent" && (
                        <div className="dn-route">
                          {routed ? (
                            <strong
                              className="agent-link"
                              title="查看 Agent 详情"
                              onClick={(e) => {
                                e.stopPropagation();
                                onAgentClick(routed);
                              }}
                            >
                              {routed}
                            </strong>
                          ) : (
                            <span className="none">无可用 Agent</span>
                          )}
                        </div>
                      )}
                      {cleanDesc(agent?.description) && (
                        <div className="dn-desc">{cleanDesc(agent?.description)}</div>
                      )}
                      {n.deps.length > 0 && <div className="dn-meta">依赖：{n.deps.join("、")}</div>}
                    </div>
                    <div className="dn-side">
                      <span className={`pill ${st}`}>{STATUS_LABEL[st] ?? st}</span>
                      {st === "waiting_human" ? (
                        <button
                          className="btn-mini"
                          onClick={(e) => {
                            e.stopPropagation();
                            onSignal(n.id);
                          }}
                        >
                          通过
                        </button>
                      ) : (
                        t && <span className="dn-time">⏱ {t}</span>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        );
      })}
    </div>
  );
}
