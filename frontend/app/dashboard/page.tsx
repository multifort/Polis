"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { api, clearTokens, getAccess, type Me, type Preset } from "@/lib/api";

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

  async function provision(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim() || !preset) return;
    setBusy(true);
    setError("");
    try {
      const res = await api.provision({ name: name.trim(), preset });
      setName("");
      setPreset("");
      await load();
      router.push(`/orgs/${res.org.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "立邦失败");
    } finally {
      setBusy(false);
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
          <div className="empty">还没有公司。选一个预设，开出你的第一家 AI 虚拟公司 👇</div>
        ) : (
          <div className="org-grid">
            {me.orgs.map((o) => (
              <Link className="org-card" href={`/orgs/${o.id}`} key={o.id}>
                <div className="name">{o.name}</div>
                <span className="badge">{o.role === "owner" ? "所有者" : o.role}</span>
              </Link>
            ))}
          </div>
        )}

        <div className="section-title">立邦 —— 按预设开一家虚拟公司</div>
        <form className="provision" onSubmit={provision}>
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
            {busy ? "立邦中…" : "立邦"}
          </button>
        </form>
        <p className="hint">选预设后，系统按模板实例化角色与 Agent（受信，直接 active）。自然语言意图与缺口生成在后续版本接入。</p>
      </div>
    </>
  );
}
