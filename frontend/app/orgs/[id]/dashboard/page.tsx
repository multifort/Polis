"use client";

// P4 看板：跨任务/场景运营统计（design v2/05 §8）。复用 plans 页的 .panel/.stat 样式。
import { useCallback, useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import AppShell from "@/components/AppShell";
import { api, getAccess, type DashboardStats } from "@/lib/api";

const STATUS_LABEL: Record<string, string> = {
  pending: "待执行",
  running: "执行中",
  done: "已完成",
  failed: "失败",
  paused: "暂停",
  needs_review: "待复核",
};

function fmtPct(v: number | null): string {
  return v == null ? "—" : `${(v * 100).toFixed(0)}%`;
}
function fmtDuration(s: number | null): string {
  if (s == null) return "—";
  const m = Math.floor(s / 60);
  const sec = Math.round(s % 60);
  return m > 0 ? `${m}分${sec}秒` : `${sec}秒`;
}
function fmtCost(v: number | null): string {
  return v == null ? "—" : `¥${v.toFixed(4)}`;
}

export default function DashboardPage() {
  const router = useRouter();
  const orgId = useParams<{ id: string }>().id;
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!getAccess()) router.replace("/");
  }, [router]);

  const load = useCallback(async () => {
    try {
      setStats(await api.dashboard(orgId));
    } catch {
      setError("加载看板数据失败");
    }
  }, [orgId]);

  useEffect(() => {
    void load();
  }, [load]);

  const maxTemplateCount = stats ? Math.max(1, ...stats.by_template.map((t) => t.count)) : 1;
  const budgetRatio =
    stats && stats.budget_cents > 0 ? stats.estimated_cost_cents / stats.budget_cents : null;

  return (
    <AppShell orgId={orgId} active="dashboard" breadcrumb="看板">
      <div className="page-head">
        <div>
          <h1 className="page-title big">看板</h1>
          <p className="muted">跨任务/场景运营统计，掌握公司整体运行状况。</p>
        </div>
      </div>

      {error && <p className="notice" style={{ marginTop: 14 }}>{error}</p>}

      {!stats ? (
        <div className="empty" style={{ marginTop: 12 }}>加载中…</div>
      ) : stats.total_runs === 0 ? (
        <div className="empty" style={{ marginTop: 12 }}>
          还没有运行记录。去「工作」出一张图、批准运行后，这里会显示统计。
        </div>
      ) : (
        <>
          {/* 核心统计卡 */}
          <div className="dash-stat-row">
            <Stat ico="Σ" label="总运行次数" value={String(stats.total_runs)} />
            <Stat ico="✓" label="成功率" value={fmtPct(stats.success_rate)} />
            <Stat ico="⏱" label="平均耗时" value={fmtDuration(stats.avg_duration_seconds)} />
            <Stat
              ico="⚡"
              label="进行中"
              value={`${stats.active_runs} / ${stats.org_max_concurrent_runs}`}
            />
          </div>
          <div className="dash-stat-row">
            <Stat ico="♻" label="复用命中率" value={fmtPct(stats.reuse_hit_rate)} />
            <Stat ico="人" label="人审通过率" value={fmtPct(stats.approval_pass_rate)} />
            <Stat
              ico="¥"
              label={`近 ${stats.recent_window} 次实测成本`}
              value={fmtCost(stats.recent_total_cost)}
            />
            <Stat
              ico="T"
              label={`近 ${stats.recent_window} 次总 token`}
              value={stats.recent_total_tokens != null ? String(stats.recent_total_tokens) : "—"}
            />
          </div>

          <div className="ops-grid" style={{ marginTop: 20 }}>
            {/* 状态分布 */}
            <section className="panel">
              <div className="panel-head">
                <h2>状态分布</h2>
              </div>
              <div className="dash-status-list">
                {Object.entries(stats.by_status).map(([status, count]) => (
                  <div className="dash-status-row" key={status}>
                    <span className={`pill ${status}`}>{STATUS_LABEL[status] ?? status}</span>
                    <div className="dash-bar-track">
                      <div
                        className={`dash-bar-fill ${status}`}
                        style={{ width: `${(count / stats.total_runs) * 100}%` }}
                      />
                    </div>
                    <span className="dash-status-count">{count}</span>
                  </div>
                ))}
              </div>
              {stats.budget_cents > 0 && (
                <div className="dash-budget-hint">
                  预算使用：¥{(stats.estimated_cost_cents / 100).toFixed(2)} / ¥
                  {(stats.budget_cents / 100).toFixed(2)}
                  {budgetRatio != null && budgetRatio >= 1 && "（已达/超预算，仅提示不阻断）"}
                </div>
              )}
            </section>

            {/* 场景分布 */}
            <section className="panel">
              <div className="panel-head">
                <h2>按场景分布</h2>
              </div>
              <div className="dash-status-list">
                {stats.by_template.map((t) => (
                  <div className="dash-status-row" key={t.template}>
                    <span className="dash-template-name" title={t.template}>
                      {t.template === "generated" ? "生成（未命中模板）" : t.template}
                    </span>
                    <div className="dash-bar-track">
                      <div
                        className={`dash-bar-fill ${t.is_template_hit ? "done" : "needs_review"}`}
                        style={{ width: `${(t.count / maxTemplateCount) * 100}%` }}
                      />
                    </div>
                    <span className="dash-status-count">{t.count}</span>
                  </div>
                ))}
              </div>
            </section>
          </div>
        </>
      )}
    </AppShell>
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
