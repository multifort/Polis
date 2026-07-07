"use client";

// C0-5 花名册：角色分组 + Agent 双栏卡（彩色头像 + 能力 pill + 在岗/待上线）+ 成员列表。
import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import AppShell from "@/components/AppShell";
import {
  api,
  getAccess,
  type Agent,
  type Member,
  type MemberRole,
  type Me,
  type Role,
} from "@/lib/api";

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
  const [me, setMe] = useState<Me | null>(null);
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState<"member" | "approver">("member");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    if (!getAccess()) {
      router.replace("/");
      return;
    }
    Promise.all([api.agents(orgId), api.roles(orgId), api.members(orgId), api.me()])
      .then(([a, r, m, current]) => {
        setAgents(a);
        setRoles(r);
        setMembers(m);
        setMe(current);
      })
      .catch(() => setAgents([]));
  }, [orgId, router]);

  const currentOrg = me?.orgs.find((o) => o.id === orgId);
  const isOwner = currentOrg?.role === "owner";
  const currentUserId = me?.user.id;

  const roleLabel = (r: string) =>
    r === "owner" ? "所有者" : r === "approver" ? "审批人" : "成员";

  // Agent 头像色（按 index 循环取色）
  const agentColor = (i: number) => AGENT_COLORS[i % AGENT_COLORS.length];

  async function reloadMembers() {
    setMembers(await api.members(orgId));
  }

  async function onInvite(e: React.FormEvent) {
    e.preventDefault();
    if (!inviteEmail.trim()) return;
    setBusy(true);
    setNotice("");
    setError("");
    try {
      const result = await api.inviteMember(orgId, {
        email: inviteEmail.trim(),
        role: inviteRole,
      });
      await reloadMembers();
      setInviteEmail("");
      if (result.status === "accepted") {
        setNotice(`${result.email} 已是成员`);
      } else if (result.invite_token) {
        setNotice(`邀请已创建，令牌：${result.invite_token}`);
      } else {
        setNotice("邀请已创建");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "邀请失败");
    } finally {
      setBusy(false);
    }
  }

  async function onRemove(member: Member) {
    if (!confirm(`移除 ${member.email}？该用户将失去当前公司的访问权限。`)) return;
    setBusy(true);
    setNotice("");
    setError("");
    try {
      await api.removeMember(orgId, member.user_id);
      await reloadMembers();
      setNotice(`${member.email} 已移除`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "移除失败");
    } finally {
      setBusy(false);
    }
  }

  async function onRoleChange(member: Member, role: MemberRole) {
    if (member.role === role) return;
    setBusy(true);
    setNotice("");
    setError("");
    try {
      const updated = await api.updateMemberRole(orgId, member.user_id, role);
      setMembers((prev) =>
        prev.map((m) => (m.user_id === updated.user_id ? { ...m, role: updated.role } : m)),
      );
      if (member.user_id === currentUserId) {
        setMe(await api.me());
      }
      setNotice(`${member.email} 已调整为${roleLabel(updated.role)}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "角色调整失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <AppShell orgId={orgId} active="roster" breadcrumb="花名册">
      <div style={{ marginBottom: 20 }}>
        <h1 className="page-title big" style={{ marginBottom: 4 }}>
          花名册
        </h1>
        <p className="muted">
          {roles.length} 个角色 · {agents?.length ?? 0} 个 Agent · {members.length} 名成员 ·
          数据与记忆按公司隔离
        </p>
      </div>

      {/* 角色 */}
      <div className="section-title">角色</div>
      <div className="role-chips" style={{ marginBottom: 22 }}>
        {roles.map((r) => (
          <span className="role-chip" key={r.id}>
            {r.name}
          </span>
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
                    {a.role ? `${a.role}` : ""}
                    {a.role && a.current_version ? " · " : ""}
                    {a.current_version ? `v${a.current_version}` : ""}
                  </div>
                </div>
                <span className={`pill ${a.status === "active" ? "done" : "pending"}`}>
                  {a.status === "active" ? "在岗" : a.status === "draft" ? "待上线" : a.status}
                </span>
              </div>
              <div className="ra-caps">
                {(a.capabilities ?? []).map((c) => (
                  <span className="cap-pill mono" key={c}>
                    {c}
                  </span>
                ))}
                {(a.capabilities ?? []).length === 0 && (
                  <span className="muted" style={{ fontSize: 11 }}>
                    暂无能力
                  </span>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {/* 成员 */}
      <div className="section-title">成员</div>
      {isOwner && (
        <form className="member-invite" onSubmit={onInvite}>
          <input
            type="email"
            value={inviteEmail}
            onChange={(e) => setInviteEmail(e.target.value)}
            placeholder="成员邮箱"
            autoComplete="email"
          />
          <select
            value={inviteRole}
            onChange={(e) => setInviteRole(e.target.value as typeof inviteRole)}
          >
            <option value="member">成员</option>
            <option value="approver">审批人</option>
          </select>
          <button className="btn-primary" type="submit" disabled={busy || !inviteEmail.trim()}>
            {busy ? "处理中…" : "邀请"}
          </button>
        </form>
      )}
      {notice && <p className="notice" style={{ marginTop: 10 }}>{notice}</p>}
      {error && <p className="error" style={{ marginTop: 10 }}>{error}</p>}
      <div className="members">
        {members.map((m) => (
          <div className="member-row" key={m.user_id}>
            <span className="shell-avatar sm">
              {m.display_name?.slice(0, 1) || m.email.slice(0, 1)}
            </span>
            <div className="member-meta">
              <div className="member-name">{m.display_name || m.email.split("@")[0]}</div>
              <div className="member-email">{m.email}</div>
            </div>
            {isOwner ? (
              <select
                className={`member-role-select${m.role === "owner" ? " owner" : ""}`}
                value={m.role}
                onChange={(e) => onRoleChange(m, e.target.value as MemberRole)}
                disabled={busy}
              >
                <option value="member">成员</option>
                <option value="approver">审批人</option>
                <option value="owner">所有者</option>
              </select>
            ) : (
              <span className={`role-chip${m.role === "owner" ? " owner" : ""}`}>
                {roleLabel(m.role)}
              </span>
            )}
            {isOwner && m.role !== "owner" && m.user_id !== currentUserId && (
              <button className="member-remove" onClick={() => onRemove(m)} disabled={busy}>
                移除
              </button>
            )}
          </div>
        ))}
      </div>
    </AppShell>
  );
}
