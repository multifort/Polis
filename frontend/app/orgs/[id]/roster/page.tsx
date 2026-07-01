"use client";

// C0-5 花名册：角色分组 + Agent 双栏卡（彩色头像 + 能力 pill + 在岗/待上线）+ 成员列表。
import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import AppShell from "@/components/AppShell";
import { api, getAccess, type Agent, type Member, type Role } from "@/lib/api";

const AGENT_COLORS = [
  ["#3F51B5", "#e8eaf6"],
  ["#757de8", "#e8eaf6"],
  ["#7e57c2", "#ede7f6"],
  ["#2e7d32", "#e8f5e9"],
  ["#ef8b1f", "#fff4e5"],
  ["#d32f2f", "#fdecea"],
];

export default function RosterPage() {
  const router = useRouter();
  const orgId = useParams<{ id: string }>().id;
  const [agents, setAgents] = useState<Agent[] | null>(null);
  const [roles, setRoles] = useState<Role[]>([]);
  const [members, setMembers] = useState<Member[]>([]);

  useEffect(() => {
    if (!getAccess()) {
      router.replace("/");
      return;
    }
    Promise.all([api.agents(orgId), api.roles(orgId), api.members(orgId)])
      .then(([a, r, m]) => {
        setAgents(a);
        setRoles(r);
        setMembers(m);
      })
      .catch(() => setAgents([]));
  }, [orgId, router]);

  const roleLabel = (r: string) =>
    r === "owner" ? "所有者" : r === "approver" ? "审批人" : "成员";

  // Agent 头像色（按 index 循环取色）
  const agentColor = (i: number) => AGENT_COLORS[i % AGENT_COLORS.length];

  return (
    <AppShell orgId={orgId} active="roster" breadcrumb="花名册">
      <div style={{ marginBottom: 20 }}>
        <h1 className="page-title big" style={{ marginBottom: 4 }}>花名册</h1>
        <p className="muted">
          {roles.length} 个角色 · {agents?.length ?? 0} 个 Agent · {members.length} 名成员 · 数据与记忆按公司隔离
        </p>
      </div>

      {/* 角色 */}
      <div className="section-title">角色</div>
      <div className="role-chips" style={{ marginBottom: 22 }}>
        {roles.map((r) => (
          <span className="role-chip" key={r.id}>{r.name}</span>
        ))}
        {roles.length === 0 && <span className="muted">暂无角色</span>}
      </div>

      {/* Agent（双栏网格） */}
      <div className="section-title">Agent（智能体）</div>
      <div className="roster-grid2">
        {(agents ?? []).map((a, i) => {
          const [fg, bg] = agentColor(i);
          const initial = (a.name ?? "A").slice(0, 1);
          return (
            <div className="roster-agent" key={a.id}>
              <div className="ra-top">
                <div className="ra-avatar" style={{ background: bg, color: fg }}>
                  {initial}
                </div>
                <div className="ra-info">
                  <div className="ra-name">{a.name}</div>
                  <div className="ra-meta">
                    {a.role ? `${a.role}` : ""}{a.role && a.current_version ? " · " : ""}
                    {a.current_version ? `v${a.current_version}` : ""}
                  </div>
                </div>
                <span className={`pill ${a.status === "active" ? "done" : "pending"}`}>
                  {a.status === "active" ? "在岗" : a.status === "draft" ? "待上线" : a.status}
                </span>
              </div>
              <div className="ra-caps">
                {(a.capabilities ?? []).map((c) => (
                  <span className="cap-pill mono" key={c}>{c}</span>
                ))}
                {(a.capabilities ?? []).length === 0 && (
                  <span className="muted" style={{ fontSize: 11 }}>暂无能力</span>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {/* 成员 */}
      <div className="section-title">成员</div>
      <div className="members">
        {members.map((m) => (
          <div className="member-row" key={m.user_id}>
            <span className="shell-avatar sm">{m.display_name?.slice(0, 1) || m.email.slice(0, 1)}</span>
            <div className="member-meta">
              <div className="member-name">{m.display_name || m.email.split("@")[0]}</div>
              <div className="member-email">{m.email}</div>
            </div>
            <span className={`role-chip${m.role === "owner" ? " owner" : ""}`}>
              {roleLabel(m.role)}
            </span>
          </div>
        ))}
      </div>
    </AppShell>
  );
}
