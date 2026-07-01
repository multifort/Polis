"use client";

// C0-2 工作列表：tabs 筛选 + 表格布局（对照原型）。
import { useCallback, useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import AppShell from "@/components/AppShell";
import { Modal } from "@/components/Modal";
import {
  api,
  downloadBlob,
  getAccess,
  type ApiError,
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
  waiting_human: "待人审",
};
const TAB_LABELS: Record<string, string> = {
  running: "执行中",
  pending: "待处理",
  done: "已完成",
  needs_review: "待复核",
  failed: "失败",
};

type TabKey = "all" | "running" | "pending_or_review" | "done";

const TABS: { key: TabKey; label: string }[] = [
  { key: "all", label: "全部" },
  { key: "running", label: "进行中" },
  { key: "pending_or_review", label: "待处理" },
  { key: "done", label: "已完成" },
];

function timeAgo(iso: string | null | undefined): string {
  if (!iso) return "—";
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "刚刚";
  if (mins < 60) return `${mins} 分钟前`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs} 小时前`;
  const days = Math.floor(hrs / 24);
  if (days < 7) return `${days} 天前`;
  return new Date(iso).toLocaleDateString("zh-CN");
}

interface TaskRowData {
  task: Task;
  latestRun: TaskRunRow | null;
  runCount: number;
}

// 按最新 run 的状态归类 tab key
function tabOf(run: TaskRunRow | null): TabKey {
  if (!run) return "all";
  if (run.status === "running") return "running";
  if (run.status === "pending" || run.status === "needs_review") return "pending_or_review";
  if (run.status === "done") return "done";
  return "all"; // failed etc. go to all
}

export default function TasksPage() {
  const router = useRouter();
  const orgId = useParams<{ id: string }>().id;

  const [tasks, setTasks] = useState<Task[]>([]);
  const [name, setName] = useState("");
  const [goal, setGoal] = useState("");
  const [creating, setCreating] = useState(false);
  const [notice, setNotice] = useState("");
  const [tab, setTab] = useState<TabKey>("all");
  const [runsByTask, setRunsByTask] = useState<Record<string, TaskRunRow[]>>({});
  const [runningId, setRunningId] = useState<string | null>(null);
  const [historyTask, setHistoryTask] = useState<TaskRowData | null>(null);
  const [exportingRun, setExportingRun] = useState<string | null>(null);

  useEffect(() => {
    if (!getAccess()) router.replace("/");
  }, [router]);

  const loadTasks = useCallback(async () => {
    try {
      const ts = await api.listTasks(orgId);
      setTasks(ts);
      // 批量拉取每个 task 的 runs，供表格显示最新运行状态
      const runsMap: Record<string, TaskRunRow[]> = {};
      await Promise.all(
        ts.map(async (t) => {
          try {
            runsMap[t.id] = await api.taskRuns(orgId, t.id);
          } catch {
            runsMap[t.id] = [];
          }
        }),
      );
      setRunsByTask(runsMap);
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

  async function onRun(taskId: string) {
    setRunningId(taskId);
    setNotice("");
    try {
      await api.runTask(orgId, taskId);
      await loadTasks();
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

  async function onExportRun(planId: string, fmt: "md" | "pdf") {
    setExportingRun(planId + fmt);
    try {
      const blob = await api.exportPlan(orgId, planId, fmt);
      downloadBlob(blob, `report_${planId}.${fmt}`);
    } catch {
      setNotice("导出失败");
    } finally {
      setExportingRun(null);
    }
  }

  // 组装表格行数据
  const rows: TaskRowData[] = tasks.map((t) => {
    const runs = runsByTask[t.id] ?? [];
    const latestRun = runs.length > 0 ? runs[0] : null;
    return { task: t, latestRun, runCount: runs.length };
  });

  // 按 tab 筛选 + 排序（有最新运行的排前面）
  const filtered =
    tab === "all"
      ? rows
      : rows.filter((r) => tabOf(r.latestRun) === tab);
  // 有 run 的排前面，按最近运行时间倒序
  const sorted = [...filtered].sort((a, b) => {
    if (a.latestRun && !b.latestRun) return -1;
    if (!a.latestRun && b.latestRun) return 1;
    return 0;
  });

  return (
    <AppShell orgId={orgId} active="work" breadcrumb="工作">
      {/* 页面头部 */}
      <div className="work-head">
        <div>
          <h1 className="page-title big">工作</h1>
          <p className="muted">保存的任务可反复运行；每条工作保留完整运行历史。</p>
        </div>
      </div>

      {/* 新建任务（紧凑行） */}
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

      {/* Tabs */}
      <div className="work-tabs">
        {TABS.map((t) => (
          <button
            key={t.key}
            className={`work-tab${tab === t.key ? " on" : ""}`}
            onClick={() => setTab(t.key)}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* 表格 */}
      {sorted.length === 0 ? (
        <div className="empty" style={{ marginTop: 12 }}>
          {tab === "all"
            ? "还没有任务，先新建一个或从工作台输入目标出图。"
            : `没有${TABS.find((t) => t.key === tab)?.label ?? ""}的任务。`}
        </div>
      ) : (
        <div className="work-table-wrap">
          <div className="work-table-head">
            <span>工作</span>
            <span>状态</span>
            <span>最近运行</span>
            <span>节点</span>
            <span>成本</span>
            <span className="right">操作</span>
          </div>
          {sorted.map((r) => {
            const run = r.latestRun;
            const runStatus = run?.status ?? "active";
            return (
              <div
                className="work-row"
                key={r.task.id}
              >
                {/* 工作 */}
                <div className="work-row-name">
                  <Link
                    href={`/orgs/${orgId}/plans${run?.plan_id ? `?plan=${run.plan_id}` : ""}`}
                    className="work-row-title"
                  >
                    {r.task.name}
                  </Link>
                  <div className="work-row-goal">{r.task.goal}</div>
                </div>
                {/* 状态 */}
                <div>
                  <span className={`pill ${runStatus}`}>
                    {STATUS_LABEL[runStatus] ?? runStatus}
                  </span>
                </div>
                {/* 最近运行 */}
                <div className="work-row-time">
                  {run
                    ? run.started_at
                      ? timeAgo(run.started_at)
                      : run.created_at
                        ? timeAgo(run.created_at)
                        : "—"
                    : "—"}
                </div>
                {/* 节点：执行记录条数，点击查看全部历次运行（P3a） */}
                <div className="work-row-nodes">
                  {r.runCount > 0 ? (
                    <button
                      className="linklike"
                      onClick={() => setHistoryTask(r)}
                      title="查看全部执行记录"
                    >
                      {r.runCount} 次
                    </button>
                  ) : (
                    "—"
                  )}
                </div>
                {/* 成本 */}
                <div className="work-row-cost">
                  {run?.actual_cost != null
                    ? `¥${run.actual_cost.toFixed(4)}`
                    : run?.estimated_cost_cents != null
                      ? `¥${(run.estimated_cost_cents / 100).toFixed(2)}`
                      : "—"}
                </div>
                {/* 操作 */}
                <div className="work-row-actions">
                  {runStatus === "waiting_human" || runStatus === "needs_review" ? (
                    <Link
                      className="btn-mini warn"
                      href={`/orgs/${orgId}/plans${run?.plan_id ? `?plan=${run.plan_id}` : ""}`}
                    >
                      去审批
                    </Link>
                  ) : null}
                  {runStatus === "running" || runStatus === "pending" ? (
                    <Link
                      className="btn-mini"
                      href={`/orgs/${orgId}/plans${run?.plan_id ? `?plan=${run.plan_id}` : ""}`}
                    >
                      查看进度
                    </Link>
                  ) : null}
                  {runStatus === "failed" ? (
                    <button
                      className="btn-mini danger"
                      onClick={() => onRun(r.task.id)}
                      disabled={runningId === r.task.id}
                    >
                      重试
                    </button>
                  ) : null}
                  {runStatus === "done" ? (
                    <button
                      className="btn-mini"
                      onClick={() => onRun(r.task.id)}
                      disabled={runningId === r.task.id}
                    >
                      再次运行
                    </button>
                  ) : null}
                  {!run && (
                    <button
                      className="btn-mini"
                      onClick={() => onRun(r.task.id)}
                      disabled={runningId === r.task.id}
                    >
                      ▶ 运行
                    </button>
                  )}
                  <Link
                    className="btn-mini ghost"
                    href={`/orgs/${orgId}/plans${run?.plan_id ? `?plan=${run.plan_id}` : ""}`}
                  >
                    查看
                  </Link>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* 执行记录（P3a）：某任务的全部历次运行，各条可查看观测/导出 */}
      {historyTask && (
        <Modal title={`执行记录 · ${historyTask.task.name}`} onClose={() => setHistoryTask(null)}>
          <div className="run-history">
            {(runsByTask[historyTask.task.id] ?? []).map((r) => (
              <div className="run-history-row" key={r.id}>
                <span className={`pill ${r.status}`}>{STATUS_LABEL[r.status] ?? r.status}</span>
                <span className="run-history-time">
                  {r.started_at ? timeAgo(r.started_at) : r.created_at ? timeAgo(r.created_at) : "—"}
                </span>
                <span className="run-history-cost">
                  {r.actual_cost != null
                    ? `¥${r.actual_cost.toFixed(4)}`
                    : r.estimated_cost_cents != null
                      ? `¥${(r.estimated_cost_cents / 100).toFixed(2)}`
                      : "—"}
                </span>
                <div className="run-history-actions">
                  {r.plan_id && (
                    <>
                      <Link className="btn-mini ghost" href={`/orgs/${orgId}/plans?plan=${r.plan_id}`}>
                        查看观测
                      </Link>
                      <button
                        className="btn-mini ghost"
                        onClick={() => void onExportRun(r.plan_id as string, "md")}
                        disabled={exportingRun === r.plan_id + "md"}
                      >
                        导出md
                      </button>
                      <button
                        className="btn-mini ghost"
                        onClick={() => void onExportRun(r.plan_id as string, "pdf")}
                        disabled={exportingRun === r.plan_id + "pdf"}
                      >
                        导出pdf
                      </button>
                    </>
                  )}
                </div>
              </div>
            ))}
          </div>
        </Modal>
      )}
    </AppShell>
  );
}
