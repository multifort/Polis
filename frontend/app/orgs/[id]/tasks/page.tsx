"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import AppShell from "@/components/AppShell";
import {
  api,
  getAccess,
  type ApiError,
  type Observability,
  type Task,
  type TaskRunRow,
} from "@/lib/api";

const STATUS_LABEL: Record<string, string> = {
  pending: "待执行",
  running: "执行中",
  done: "已完成",
  failed: "失败",
  paused: "暂停",
  active: "可用",
  needs_review: "待复核",
  needs_rework: "待返工",
};
const fmtCost = (y: number | null | undefined) => (y == null ? "—" : `¥${y.toFixed(4)}`);
const fmtNum = (n: number | null | undefined) => (n == null ? "—" : n.toLocaleString());

export default function TasksPage() {
  const router = useRouter();
  const orgId = useParams<{ id: string }>().id;

  const [tasks, setTasks] = useState<Task[]>([]);
  const [name, setName] = useState("");
  const [goal, setGoal] = useState("");
  const [creating, setCreating] = useState(false);
  const [notice, setNotice] = useState("");
  const [expanded, setExpanded] = useState<string | null>(null);
  const [runs, setRuns] = useState<Record<string, TaskRunRow[]>>({});
  const [runningId, setRunningId] = useState<string | null>(null);
  const [obs, setObs] = useState<Observability | null>(null);
  const [obsLoading, setObsLoading] = useState(false);

  useEffect(() => {
    if (!getAccess()) router.replace("/");
  }, [router]);

  const loadTasks = useCallback(async () => {
    try {
      setTasks(await api.listTasks(orgId));
    } catch {
      setNotice("加载任务失败");
    }
  }, [orgId]);

  useEffect(() => {
    loadTasks();
  }, [loadTasks]);

  async function onCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim() || !goal.trim()) return;
    setCreating(true);
    setNotice("");
    try {
      await api.createTask(orgId, { name: name.trim(), goal: goal.trim() });
      setName("");
      setGoal("");
      await loadTasks();
    } catch {
      setNotice("创建任务失败");
    } finally {
      setCreating(false);
    }
  }

  const loadRuns = useCallback(
    async (taskId: string) => {
      try {
        setRuns((m) => ({ ...m, [taskId]: [] }));
        const r = await api.taskRuns(orgId, taskId);
        setRuns((m) => ({ ...m, [taskId]: r }));
      } catch {
        setNotice("加载执行记录失败");
      }
    },
    [orgId],
  );

  async function onToggle(taskId: string) {
    if (expanded === taskId) {
      setExpanded(null);
      return;
    }
    setExpanded(taskId);
    await loadRuns(taskId);
  }

  async function onRun(taskId: string) {
    setRunningId(taskId);
    setNotice("");
    try {
      await api.runTask(orgId, taskId);
      setExpanded(taskId);
      await loadRuns(taskId);
    } catch (err) {
      const s = (err as ApiError).status;
      setNotice(
        s === 503
          ? "编排服务未就绪，暂时无法运行任务"
          : s === 404
            ? "当前公司能力不足以匹配任何计划模板"
            : "运行任务失败",
      );
    } finally {
      setRunningId(null);
    }
  }

  async function viewRun(planId: string | null | undefined) {
    if (!planId) return;
    setObsLoading(true);
    setObs(null);
    try {
      setObs(await api.planObservability(orgId, planId));
    } catch (err) {
      const s = (err as ApiError).status;
      setNotice(s === 404 ? "该运行暂无观测数据" : "加载观测失败");
    } finally {
      setObsLoading(false);
    }
  }

  return (
    <>
      <AppShell orgId={orgId} active="work" breadcrumb="工作">
        <div className="page-head">
          <div>
            <h1 className="page-title big">工作</h1>
            <p className="muted">保存的任务可反复运行；每条工作保留完整运行历史。</p>
          </div>
          <Link className="btn-primary" href={`/orgs/${orgId}`}>
            ＋ 新目标
          </Link>
        </div>

        <form className="task-create" onSubmit={onCreate}>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="任务名称，如：供应商交付分析"
          />
          <input
            value={goal}
            onChange={(e) => setGoal(e.target.value)}
            placeholder="目标，如：分析供应商交付"
          />
          <button className="btn-primary" type="submit" disabled={creating}>
            {creating ? "创建中…" : "＋ 新建任务"}
          </button>
        </form>

        {notice && <p className="notice" style={{ marginTop: 14 }}>{notice}</p>}

        <div className="task-list">
          {tasks.length === 0 && <p className="empty">还没有任务，先新建一个。</p>}
          {tasks.map((t) => (
            <div className="task-card" key={t.id}>
              <div className="task-row">
                <div className="task-meta" onClick={() => onToggle(t.id)}>
                  <span className="task-name">{t.name}</span>
                  <span className="task-goal">{t.goal}</span>
                </div>
                <div className="task-actions">
                  <button
                    className="btn-run"
                    onClick={() => onRun(t.id)}
                    disabled={runningId === t.id}
                  >
                    {runningId === t.id ? "启动中…" : "▶ 运行"}
                  </button>
                  <button className="icon-btn" onClick={() => onToggle(t.id)}>
                    {expanded === t.id ? "收起" : "执行记录"}
                  </button>
                </div>
              </div>

              {expanded === t.id && (
                <div className="task-runs">
                  {(runs[t.id] ?? []).length === 0 && (
                    <p className="hint">暂无执行记录（点「运行」开始一次）。</p>
                  )}
                  {(runs[t.id] ?? []).map((r, i) => (
                    <div className="run-row" key={r.id}>
                      <span className="run-idx">#{(runs[t.id] ?? []).length - i}</span>
                      <span className={`pill ${r.status}`}>
                        {STATUS_LABEL[r.status] ?? r.status}
                      </span>
                      <span className="run-id">run {r.id.slice(0, 8)}</span>
                      <button className="link-btn" onClick={() => viewRun(r.plan_id)}>
                        查看观测 ›
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      </AppShell>

      {(obs || obsLoading) && (
        <div className="modal-overlay" onClick={() => setObs(null)}>
          <div className="modal log-modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-head">
              <h3>运行观测</h3>
              <button className="modal-x" onClick={() => setObs(null)}>
                ×
              </button>
            </div>
            {obsLoading && <p className="hint">加载中…</p>}
            {obs && (
              <>
                <div className="obs-chips" style={{ marginBottom: 12 }}>
                  <span className="role-chip">{STATUS_LABEL[obs.status] ?? obs.status}</span>
                  <span className="role-chip">{obs.nodes.length} 节点产出</span>
                  <span className="role-chip">
                    {fmtNum(obs.totals.total_tokens)} tokens · {fmtCost(obs.totals.cost)}
                  </span>
                </div>
                <div className="log-body">
                  {obs.nodes.map((n, i) => (
                    <details className={`obs-node ${n.status}`} key={n.node_id} open={i === 0}>
                      <summary>
                        <span className="oid">{n.node_id}</span>
                        <span className={`pill ${n.status}`}>
                          {STATUS_LABEL[n.status] ?? n.status}
                        </span>
                      </summary>
                      <div className="md">
                        {(n.content ?? n.summary) ? (
                          <ReactMarkdown remarkPlugins={[remarkGfm]}>
                            {n.content ?? n.summary}
                          </ReactMarkdown>
                        ) : (
                          <p className="hint">（无产出文本）</p>
                        )}
                      </div>
                    </details>
                  ))}
                  {obs.nodes.length === 0 && <p className="hint">该运行暂无节点产出。</p>}
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </>
  );
}
