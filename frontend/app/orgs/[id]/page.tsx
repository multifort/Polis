"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { api, getAccess, type Agent, type Me, type Member, type Org, type Role } from "@/lib/api";

export default function OrgDetailPage() {
  const router = useRouter();
  const params = useParams<{ id: string }>();
  const orgId = params.id;
  const [me, setMe] = useState<Me | null>(null);
  const [org, setOrg] = useState<Org | null>(null);
  const [agents, setAgents] = useState<Agent[] | null>(null);
  const [roles, setRoles] = useState<Role[]>([]);
  const [members, setMembers] = useState<Member[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!getAccess()) {
      router.replace("/");
      return;
    }
    (async () => {
      try {
        const meData = await api.me();
        setMe(meData);
        setOrg(meData.orgs.find((o) => o.id === orgId) ?? null);
        const [a, r, m] = await Promise.all([
          api.agents(orgId),
          api.roles(orgId),
          api.members(orgId),
        ]);
        setAgents(a);
        setRoles(r);
        setMembers(m);
      } catch (err) {
        setError(err instanceof Error ? err.message : "加载失败");
      }
    })();
  }, [orgId, router]);

  return (
    <>
      <div className="topbar">
        <div className="brand">
          <div className="logo">A</div>
          <span className="brand-name">Polis</span>
        </div>
        <div className="right">
          {me && me.orgs.length > 1 && (
            <span className="switcher">
              <select value={orgId} onChange={(e) => router.push(`/orgs/${e.target.value}`)}>
                {me.orgs.map((o) => (
                  <option value={o.id} key={o.id}>{o.name}</option>
                ))}
              </select>
            </span>
          )}
          <Link className="back" href="/dashboard">← 我的公司</Link>
        </div>
      </div>

      <div className="container">
        {error && <p className="error">{error}</p>}
        {agents === null ? (
          <p className="muted">加载中…</p>
        ) : (
          <>
            <div className="page-head">
              <div>
                <h1 className="page-title">{org?.name ?? "公司"}</h1>
                {org?.description && <p className="muted">{org.description}</p>}
                <p className="muted">
                  花名册 · {agents.length} 个 Agent · {roles.length} 个角色 · {members.length} 名成员 · 数据/记忆按公司隔离
                </p>
              </div>
              <Link className="btn-mini" href={`/orgs/${orgId}/plans`}>
                任务 / 计划 →
              </Link>
            </div>

            <div className="section-title">角色</div>
            <div className="role-chips">
              {roles.map((r) => (
                <span className="role-chip" key={r.id}>{r.name}</span>
              ))}
            </div>

            <div className="section-title">Agent（智能体）</div>
            <div className="roster">
              {agents.map((a) => (
                <div className="agent-row" key={a.id}>
                  <div>
                    <div className="name">{a.name}</div>
                    <div className="meta">来源 {a.source} · 版本 {a.current_version ?? "-"}</div>
                  </div>
                  <span className={`pill ${a.status === "active" ? "active" : "draft"}`}>
                    {a.status === "active" ? "已上线" : a.status}
                  </span>
                </div>
              ))}
            </div>

            <div className="section-title">成员</div>
            <div className="members">
              {members.map((m) => (
                <div className="member-row" key={m.user_id}>
                  <div className="avatar">{(m.display_name || m.email)[0]?.toUpperCase()}</div>
                  <div className="who">
                    <div className="name">{m.display_name || m.email}</div>
                    <div className="em">{m.email}</div>
                  </div>
                  <span className="badge">{m.role === "owner" ? "所有者" : m.role === "approver" ? "审批人" : "成员"}</span>
                </div>
              ))}
            </div>
          </>
        )}
      </div>
    </>
  );
}
