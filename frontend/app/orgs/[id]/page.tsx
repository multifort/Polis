"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { api, getAccess, type Agent, type Role } from "@/lib/api";

export default function OrgDetailPage() {
  const router = useRouter();
  const params = useParams<{ id: string }>();
  const orgId = params.id;
  const [orgName, setOrgName] = useState("");
  const [agents, setAgents] = useState<Agent[] | null>(null);
  const [roles, setRoles] = useState<Role[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!getAccess()) {
      router.replace("/");
      return;
    }
    (async () => {
      try {
        const me = await api.me();
        const org = me.orgs.find((o) => o.id === orgId);
        setOrgName(org?.name ?? "公司");
        const [a, r] = await Promise.all([api.agents(orgId), api.roles(orgId)]);
        setAgents(a);
        setRoles(r);
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
                <h1 className="page-title">{orgName}</h1>
                <p className="muted">花名册 · {agents.length} 个 Agent · {roles.length} 个角色 · 数据/记忆按公司隔离</p>
              </div>
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
          </>
        )}
      </div>
    </>
  );
}
