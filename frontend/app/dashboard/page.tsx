"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api, clearTokens, getAccess, type Me, type Org, type Preset } from "@/lib/api";

export default function DashboardPage() {
  const router = useRouter();
  const [me, setMe] = useState<Me | null>(null);
  const [presets, setPresets] = useState<Preset[]>([]);
  const [name, setName] = useState("");
  const [preset, setPreset] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

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
    api.listPresets().then(setPresets).catch(() => {});
  }, [router]);

  async function createCompany(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim() || !preset) return;
    setBusy(true);
    setError("");
    try {
      const res = await api.provision({ name: name.trim(), preset });
      setName("");
      setPreset("");
      router.push(`/orgs/${res.org.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "创建失败");
    } finally {
      setBusy(false);
    }
  }

  async function rename(o: Org) {
    const next = window.prompt("修改公司名称", o.name);
    if (!next || !next.trim() || next.trim() === o.name) return;
    try {
      await api.renameOrg(o.id, next.trim());
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "重命名失败");
    }
  }

  async function remove(o: Org) {
    if (!window.confirm(`删除「${o.name}」？该公司下的角色、Agent、记忆将一并删除，且不可恢复。`)) return;
    try {
      await api.deleteOrg(o.id);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "删除失败");
    }
  }

  function logout() {
    clearTokens();
    router.replace("/");
  }

  if (!me) {
    return (
      <div className="container">
        <p className="muted">{error || "加载中…"}</p>
      </div>
    );
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
            <h1 className="page-title">我的公司</h1>
            <p className="muted">共 {me.orgs.length} 家 · 每家虚拟公司数据独立、记忆独立</p>
          </div>
        </div>

        {error && <p className="error">{error}</p>}

        {me.orgs.length === 0 ? (
          <div className="empty">还没有公司。选一个预设，创建你的第一家 AI 虚拟公司 👇</div>
        ) : (
          <div className="org-grid">
            {me.orgs.map((o) => (
              <div className="org-card" key={o.id}>
                <div className="head" onClick={() => router.push(`/orgs/${o.id}`)}>
                  <div className="org-icon">{o.name[0]}</div>
                  <div>
                    <div className="name">{o.name}</div>
                    <span className="badge">{o.role === "owner" ? "所有者" : o.role}</span>
                  </div>
                </div>
                {o.role === "owner" && (
                  <div className="card-actions">
                    <button className="icon-btn" onClick={() => rename(o)}>重命名</button>
                    <button className="icon-btn danger" onClick={() => remove(o)}>删除</button>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}

        <div className="section-title">新建虚拟公司</div>
        <div className="wizard">
          <h3><span className="dot" />按预设创建一家虚拟公司</h3>
          <form className="provision" onSubmit={createCompany}>
            <select value={preset} onChange={(e) => setPreset(e.target.value)}>
              <option value="">选择预设…</option>
              {presets.map((p) => (
                <option value={p.name} key={`${p.name}@${p.version}`}>
                  {p.name}（{p.description}）
                </option>
              ))}
            </select>
            <input value={name} onChange={(e) => setName(e.target.value)} placeholder="公司名称" />
            <button className="btn-primary" type="submit" disabled={busy || !preset || !name.trim()}>
              {busy ? "创建中…" : "创建"}
            </button>
          </form>
          <p className="hint">选预设后，系统按模板实例化角色与 Agent（受信，直接上线）。自然语言意图与缺口生成在后续版本接入。</p>
        </div>
      </div>
    </>
  );
}
