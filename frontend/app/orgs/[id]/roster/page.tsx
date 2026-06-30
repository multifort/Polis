"use client";

// C0-1 花名册（从原公司 hub 迁来，套进 AppShell）。视觉精修留 C0-5。
import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import AppShell from "@/components/AppShell";
import { api, getAccess, type Agent, type Member, type Role } from "@/lib/api";

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

  return (
    <AppShell orgId={orgId} active="roster" breadcrumb="花名册">
      <div className="page-head">
        <h1 className="page-title big">花名册</h1>
        <p className="muted">
          {roles.length} 个角色 · {agents?.length ?? 0} 个 Agent · {members.length} 名成员 · 数据与记忆按公司隔离
        </p>
      </div>

      <div className="section-title">角色</div>
      <div className="role-chips">
        {roles.map((r) => (
          <span className="role-chip" key={r.id}>{r.name}</span>
        ))}
      </div>

      <div className="section-title">Agent（智能体）</div>
      <div className="roster-grid">
        {(agents ?? []).map((a) => (
          <div className="agent-card" key={a.id}>
            <div className="agent-card-head">
              <span className="agent-card-name">{a.name}</span>
              <span className={`pill ${a.status === "active" ? "active" : "draft"}`}>
                {a.status === "active" ? "在岗" : a.status === "draft" ? "待上线" : a.status}
              </span>
            </div>
            <div className="agent-card-meta">
              {a.role ? `${a.role} · ` : ""}{a.current_version ?? "v1"}
            </div>
            <div className="agent-card-caps">
              {(a.capabilities ?? []).map((c) => (
                <span className="cap-pill" key={c}>{c}</span>
              ))}
            </div>
          </div>
        ))}
      </div>

      <div className="section-title">成员</div>
      <div className="members">
        {members.map((m) => (
          <div className="member-row" key={m.user_id}>
            <span className="shell-avatar sm">{(m.display_name || m.email).slice(0, 1)}</span>
            <div className="member-meta">
              <div className="member-name">{m.display_name || m.email.split("@")[0]}</div>
              <div className="member-email">{m.email}</div>
            </div>
            <span className="role-chip">{roleLabel(m.role)}</span>
          </div>
        ))}
      </div>
    </AppShell>
  );
}
