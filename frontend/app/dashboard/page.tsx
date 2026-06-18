"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api, clearTokens, getAccess, type Me } from "@/lib/api";

export default function DashboardPage() {
  const router = useRouter();
  const [me, setMe] = useState<Me | null>(null);
  const [error, setError] = useState("");
  const [newName, setNewName] = useState("");
  const [creating, setCreating] = useState(false);

  async function load() {
    try {
      setMe(await api.me());
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载失败");
    }
  }

  useEffect(() => {
    if (!getAccess()) {
      router.replace("/");
      return;
    }
    load();
  }, [router]);

  async function createOrg(e: React.FormEvent) {
    e.preventDefault();
    if (!newName.trim()) return;
    setCreating(true);
    try {
      await api.createOrg({ name: newName.trim() });
      setNewName("");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "创建失败");
    } finally {
      setCreating(false);
    }
  }

  function logout() {
    clearTokens();
    router.replace("/");
  }

  if (!me) {
    return <div className="container"><p className="muted">{error || "加载中…"}</p></div>;
  }

  const initial = (me.user.display_name || me.user.email)[0]?.toUpperCase() ?? "U";

  return (
    <>
      <div className="topbar">
        <div className="brand">
          <div className="logo">A</div>
          <span className="brand-name">Polis</span>
        </div>
        <div className="right">
          <span>{me.user.display_name || me.user.email}</span>
          <div className="avatar">{initial}</div>
          <button className="link-btn" onClick={logout}>退出</button>
        </div>
      </div>

      <div className="container">
        <div className="page-head">
          <div>
            <h1 className="page-title">我的城邦</h1>
            <p className="muted">共 {me.orgs.length} 座 · 每座城邦数据独立、记忆独立</p>
          </div>
        </div>

        {error && <p className="error">{error}</p>}

        {me.orgs.length === 0 ? (
          <div className="empty">还没有城邦。给它起个名字，立你的第一座城邦 👇</div>
        ) : (
          <div className="org-grid">
            {me.orgs.map((o) => (
              <div className="org-card" key={o.id}>
                <div className="name">{o.name}</div>
                <span className="badge">{o.role === "owner" ? "所有者" : o.role}</span>
              </div>
            ))}
          </div>
        )}

        <form className="inline-form" onSubmit={createOrg}>
          <input value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="新城邦名称，如：采购分析公司" />
          <button className="btn-primary" style={{ width: "auto", padding: "0 18px", height: 36 }} type="submit" disabled={creating}>
            {creating ? "创建中…" : "立邦"}
          </button>
        </form>
      </div>
    </>
  );
}
