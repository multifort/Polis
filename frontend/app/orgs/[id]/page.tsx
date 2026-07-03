"use client";

// C0-1/C0-4 工作台首屏：问候 + 目标输入「出图」+ 快捷 chips + 需要你处理(审批) + 进行中 + 最近产出。
import { useCallback, useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import AppShell from "@/components/AppShell";
import { api, getAccess, type ApprovalRow, type DashboardStats, type Me, type WorkspaceRuns, type WorkspaceRunItem } from "@/lib/api";

const CHIPS = ["分析本季度供应商交付准时率，并给出改进建议", "对 3 家供应商询价比价并出采购建议", "生成本月支出结构报告"];
const STATUS_LABEL: Record<string, string> = {
  draft: "草稿", active: "可用", running: "执行中", done: "已完成",
  failed: "失败", needs_review: "待复核", pending: "待执行",
};

function greeting(): string {
  const h = new Date().getHours();
  return h < 6 ? "凌晨好" : h < 12 ? "上午好" : h < 14 ? "中午好" : h < 18 ? "下午好" : "晚上好";
}

function elapsed(iso: string | null): string {
  if (!iso) return "";
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "刚刚";
  if (mins < 60) return `${mins} 分钟`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs} 小时`;
  const days = Math.floor(hrs / 24);
  return `${days} 天`;
}

function timeAgo(iso: string | null): string {
  if (!iso) return "";
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

export default function WorkbenchPage() {
  const router = useRouter();
  const orgId = useParams<{ id: string }>().id;
  const [me, setMe] = useState<Me | null>(null);
  const [goal, setGoal] = useState("");
  const [approvals, setApprovals] = useState<ApprovalRow[]>([]);
  const [runs, setRuns] = useState<WorkspaceRuns>({ active: [], recent: [] });
  const [stats, setStats] = useState<DashboardStats | null>(null);

  useEffect(() => {
    if (!getAccess()) {
      router.replace("/");
      return;
    }
    api.me().then(setMe).catch(() => undefined);
    api.listApprovals(orgId).then(setApprovals).catch(() => setApprovals([]));
    api.workspaceRuns(orgId).then(setRuns).catch(() => setRuns({ active: [], recent: [] }));
    api.dashboard(orgId).then(setStats).catch(() => undefined);
  }, [orgId, router]);

  const org = me?.orgs.find((o) => o.id === orgId) ?? null;
  const userName = me?.user.display_name || me?.user.email?.split("@")[0] || "你";

  const submit = useCallback(() => {
    const g = goal.trim();
    if (!g) return;
    router.push(`/orgs/${orgId}/plans?goal=${encodeURIComponent(g)}`);
  }, [goal, orgId, router]);

  const activeRuns = runs.active;
  const recentRuns = runs.recent;

  return (
    <AppShell orgId={orgId} active="home" breadcrumb="工作台" workBadge={approvals.length || undefined}>
      {/* Hero：目标输入 */}
      <section className="wb-hero">
        <h1>
          {greeting()}，{userName} <span className="wave">👋</span> 想让{org?.name ?? "这家公司"}做点什么？
        </h1>
        <p>输入一个目标，系统会出一张执行计划，批准后交给角色化 Agent 协作完成。</p>
        <div className="wb-goalbar">
          <input
            value={goal}
            onChange={(e) => setGoal(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && submit()}
            placeholder="例如：分析本季度供应商交付准时率，并给出改进建议"
          />
          <button onClick={submit}>✦ 出图</button>
        </div>
        <div className="wb-chips">
          {CHIPS.map((c) => (
            <button key={c} className="wb-chip" onClick={() => setGoal(c)}>
              {c.length > 14 ? c.slice(0, 14) + "…" : c}
            </button>
          ))}
        </div>
      </section>

      {/* 需要你处理（审批收件箱）*/}
      {approvals.length > 0 && (
        <section className="wb-block">
          <div className="wb-block-head">
            <h2>需要你处理</h2>
            <span className="wb-count">{approvals.length}</span>
          </div>
          <div className="wb-attn-grid">
            {approvals.slice(0, 4).map((a) => (
              <div className="wb-attn" key={a.id}>
                <div className="wb-attn-ic">!</div>
                <div className="wb-attn-body">
                  <div className="wb-attn-title">
                    {String((a.payload?.reason as string) || "待审批")} · {a.kind}
                  </div>
                  <div className="wb-attn-sub">
                    {a.payload?.node_id ? `节点「${String(a.payload.node_id)}」 · ` : ""}等待你处理
                  </div>
                </div>
                <Link className="btn-mini" href={`/orgs/${orgId}/plans${a.ref_id ? `?plan=${a.ref_id}` : ""}`}>
                  去审批
                </Link>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* 数据看板（Hero 下方，进行中/最近产出上方） */}
      {stats && stats.total_runs > 0 && (
        <div className="wb-dashboard-section">
          <div className="dash-stat-row">
            <Stat ico="Σ" label="总运行次数" value={String(stats.total_runs)} />
            <Stat ico="✓" label="成功率" value={stats.success_rate != null ? `${(stats.success_rate * 100).toFixed(0)}%` : "—"} />
            <Stat ico="⏱" label="平均耗时" value={stats.avg_duration_seconds != null ? `${Math.floor(stats.avg_duration_seconds / 60)}分${Math.round(stats.avg_duration_seconds % 60)}秒` : "—"} />
            <Stat ico="⚡" label="进行中" value={String(stats.active_runs)} />
          </div>
          <div className="dash-stat-row">
            <Stat ico="♻" label="复用命中率" value={stats.reuse_hit_rate != null ? `${(stats.reuse_hit_rate * 100).toFixed(0)}%` : "—"} />
            <Stat ico="人" label="人审通过率" value={stats.approval_pass_rate != null ? `${(stats.approval_pass_rate * 100).toFixed(0)}%` : "—"} />
            <Stat ico="¥" label={`近 ${stats.recent_window} 次成本`} value={stats.recent_total_cost != null ? `¥${stats.recent_total_cost.toFixed(4)}` : "—"} />
            <Stat ico="T" label={`近 ${stats.recent_window} 次 token`} value={stats.recent_total_tokens != null ? String(stats.recent_total_tokens) : "—"} />
          </div>
          <div className="ops-grid" style={{ marginTop: 20 }}>
            <section className="panel">
              <div className="panel-head"><h2>状态分布</h2></div>
              <div className="dash-status-list">
                {Object.entries(stats.by_status).map(([status, count]) => (
                  <div className="dash-status-row" key={status}>
                    <span className={`pill ${status}`}>{STATUS_LABEL[status] ?? status}</span>
                    <div className="dash-bar-track">
                      <div className={`dash-bar-fill ${status}`} style={{ width: `${(count / stats.total_runs) * 100}%` }} />
                    </div>
                    <span className="dash-status-count">{count}</span>
                  </div>
                ))}
              </div>
            </section>
            <section className="panel">
              <div className="panel-head"><h2>场景分布</h2></div>
              <div className="dash-status-list">
                {stats.by_template.map((t) => (
                  <div className="dash-status-row" key={t.template}>
                    <span className="dash-template-name">{t.template === "generated" ? "生成（未命中模板）" : t.template}</span>
                    <div className="dash-bar-track">
                      <div className={`dash-bar-fill ${t.is_template_hit ? "done" : "needs_review"}`}
                        style={{ width: `${(t.count / Math.max(1, ...stats.by_template.map(x => x.count))) * 100}%` }} />
                    </div>
                    <span className="dash-status-count">{t.count}</span>
                  </div>
                ))}
              </div>
            </section>
          </div>
        </div>
      )}

      {/* 进行中 + 最近产出（双栏）*/}
      <div className="wb-duo">
        {/* 进行中 */}
        <section className="wb-block">
          <div className="wb-recent-box">
            <div className="wb-recent-head">
              <h2>进行中</h2>
              {activeRuns.length > 0 && <span className="wb-count">{activeRuns.length}</span>}
            </div>
            {activeRuns.length === 0 ? (
              <div className="wb-empty-state">
                <div className="wb-empty-ico">⚡</div>
                <p>暂无进行中的工作</p>
                <p className="wb-empty-sub">输入目标出图并批准后，进行中的运行会出现在这里</p>
              </div>
            ) : (
              <div className="wb-active-list">
                {activeRuns.map((r) => (
                  <RunCard key={r.run_id} run={r} orgId={orgId} active />
                ))}
              </div>
            )}
          </div>
        </section>

        {/* 最近产出 */}
        <section className="wb-block">
          <div className="wb-recent-box">
            <div className="wb-recent-head">
              <h2>最近产出</h2>
              <Link className="wb-more" href={`/orgs/${orgId}/tasks`}>
                查看全部 ›
              </Link>
            </div>
            {recentRuns.length === 0 ? (
              <div className="wb-empty-state">
                <div className="wb-empty-ico">📋</div>
                <p>暂无完成的产出</p>
                <p className="wb-empty-sub">运行完成后的产出摘要会出现在这里</p>
              </div>
            ) : (
              <div className="wb-recent-cards">
                {recentRuns.map((r) => (
                  <RunCard key={r.run_id} run={r} orgId={orgId} />
                ))}
              </div>
            )}
          </div>
        </section>
      </div>

    </AppShell>
  );
}

function RunCard({ run, orgId, active }: { run: WorkspaceRunItem; orgId: string; active?: boolean }) {
  const name = run.task_name || "临时运行";
  const href = run.task_id
    ? `/orgs/${orgId}/tasks`
    : `/orgs/${orgId}/plans${run.plan_id ? `?plan=${run.plan_id}` : ""}`;

  if (active) {
    // 进行中：卡片 + 进度条 + 节点/成本信息
    const costStr = run.actual_cost != null ? `¥${run.actual_cost.toFixed(4)}` : null;
    const sub = [
      run.run_status === "pending" ? "等待启动" : `已运行 ${elapsed(run.started_at)}`,
      run.node_count > 0 ? `${run.node_count} 个节点` : null,
      costStr,
    ].filter(Boolean).join(" · ");
    return (
      <Link className="wb-active-card" href={href}>
        <div className="wb-active-top">
          <span className="wb-active-name">{name}</span>
          <span className={`pill ${run.run_status}`}>
            {STATUS_LABEL[run.run_status] ?? run.run_status}
          </span>
        </div>
        <div className="wb-active-bar"><div className="wb-active-fill" /></div>
        <div className="wb-active-sub">{sub}</div>
      </Link>
    );
  }

  // 最近产出：紧凑行（✓ + 名称 + 时间·成本·节点 + 查看按钮）
  const costStr = run.actual_cost != null ? `¥${run.actual_cost.toFixed(4)}` : null;
  const meta = [
    timeAgo(run.finished_at),
    costStr,
    run.node_count > 0 ? `${run.node_count} 节点` : null,
    run.run_status === "failed" ? STATUS_LABEL[run.run_status] : null,
  ].filter(Boolean).join(" · ");

  return (
    <Link className="wb-recent-card" href={href}>
      <span className="wb-recent-check">✓</span>
      <div className="wb-recent-main">
        <div className="wb-recent-name">{name}</div>
        <div className="wb-recent-sub">{meta}</div>
      </div>
      <span className="wb-recent-btn">查看</span>
    </Link>
  );
}

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
