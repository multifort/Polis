"use client";

// C0-1 工作台首屏：问候 + 目标输入「出图」+ 快捷 chips + 需要你处理(审批) + 最近工作。
// （进行中/最近产出 的逐 run 卡片留 C0-4，需跨任务 run 列表端点）
import { useCallback, useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import AppShell from "@/components/AppShell";
import { api, getAccess, type ApprovalRow, type Me, type Task } from "@/lib/api";

const CHIPS = ["分析本季度供应商交付准时率，并给出改进建议", "对 3 家供应商询价比价并出采购建议", "生成本月支出结构报告"];
const STATUS_LABEL: Record<string, string> = {
  draft: "草稿", active: "可用", running: "执行中", done: "已完成",
  failed: "失败", needs_review: "待复核", pending: "待执行",
};

function greeting(): string {
  const h = new Date().getHours();
  return h < 6 ? "凌晨好" : h < 12 ? "上午好" : h < 14 ? "中午好" : h < 18 ? "下午好" : "晚上好";
}

export default function WorkbenchPage() {
  const router = useRouter();
  const orgId = useParams<{ id: string }>().id;
  const [me, setMe] = useState<Me | null>(null);
  const [goal, setGoal] = useState("");
  const [approvals, setApprovals] = useState<ApprovalRow[]>([]);
  const [tasks, setTasks] = useState<Task[]>([]);

  useEffect(() => {
    if (!getAccess()) {
      router.replace("/");
      return;
    }
    api.me().then(setMe).catch(() => undefined);
    api.listApprovals(orgId).then(setApprovals).catch(() => setApprovals([]));
    api.listTasks(orgId).then(setTasks).catch(() => setTasks([]));
  }, [orgId, router]);

  const org = me?.orgs.find((o) => o.id === orgId) ?? null;
  const userName = me?.user.display_name || me?.user.email?.split("@")[0] || "你";

  const submit = useCallback(() => {
    const g = goal.trim();
    if (!g) return;
    router.push(`/orgs/${orgId}/plans?goal=${encodeURIComponent(g)}`);
  }, [goal, orgId, router]);

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

      {/* 最近工作（C0-4 将拆「进行中 / 最近产出」逐 run 卡）*/}
      <section className="wb-block">
        <div className="wb-block-head">
          <h2>最近工作</h2>
          <Link className="wb-more" href={`/orgs/${orgId}/tasks`}>
            查看全部 ›
          </Link>
        </div>
        {tasks.length === 0 ? (
          <p className="wb-empty">还没有工作。在上面输入一个目标试试 →</p>
        ) : (
          <div className="wb-work-list">
            {tasks.slice(0, 6).map((t) => (
              <Link className="wb-work" key={t.id} href={`/orgs/${orgId}/tasks`}>
                <div className="wb-work-main">
                  <span className="wb-work-name">{t.name}</span>
                  <span className="wb-work-goal">{t.goal}</span>
                </div>
                <span className={`pill ${t.status}`}>{STATUS_LABEL[t.status] ?? t.status}</span>
              </Link>
            ))}
          </div>
        )}
      </section>
    </AppShell>
  );
}
