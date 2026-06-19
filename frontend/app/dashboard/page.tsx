"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api, clearTokens, getAccess, type Me, type Org, type Preset } from "@/lib/api";
import { Modal } from "@/components/Modal";

export default function DashboardPage() {
  const router = useRouter();
  const [me, setMe] = useState<Me | null>(null);
  const [presets, setPresets] = useState<Preset[]>([]);
  const [name, setName] = useState("");
  const [desc, setDesc] = useState("");
  const [preset, setPreset] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const [editing, setEditing] = useState<Org | null>(null);
  const [editName, setEditName] = useState("");
  const [editDesc, setEditDesc] = useState("");
  const [deleting, setDeleting] = useState<Org | null>(null);

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
      const res = await api.provision({
        name: name.trim(),
        preset,
        description: desc.trim() || undefined,
      });
      router.push(`/orgs/${res.org.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "创建失败");
    } finally {
      setBusy(false);
    }
  }

  function openEdit(o: Org) {
    setEditName(o.name);
    setEditDesc(o.description ?? "");
    setEditing(o);
  }

  async function saveEdit(e: React.FormEvent) {
    e.preventDefault();
    if (!editing || !editName.trim()) return;
    try {
      await api.updateOrg(editing.id, editName.trim(), editDesc.trim() || null);
      setEditing(null);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存失败");
    }
  }

  async function confirmDelete() {
    if (!deleting) return;
    try {
      await api.deleteOrg(deleting.id);
      setDeleting(null);
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
                {o.description && <p className="card-desc">{o.description}</p>}
                {o.role === "owner" && (
                  <div className="card-actions">
                    <button className="icon-btn" onClick={() => openEdit(o)}>编辑</button>
                    <button className="icon-btn danger" onClick={() => setDeleting(o)}>删除</button>
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
          <input
            style={{ width: "100%", height: 42, marginTop: 10, padding: "0 14px", border: "1px solid var(--color-border-strong)", borderRadius: 10, fontSize: 14 }}
            value={desc}
            onChange={(e) => setDesc(e.target.value)}
            placeholder="公司描述（可选，留空则用预设描述）"
          />
          <p className="hint">选预设后，系统按模板实例化角色与 Agent（受信，直接上线）。自然语言意图与缺口生成在后续版本接入。</p>
        </div>
      </div>

      {editing && (
        <Modal title="编辑公司" onClose={() => setEditing(null)}>
          <form onSubmit={saveEdit}>
            <label>公司名称</label>
            <input value={editName} onChange={(e) => setEditName(e.target.value)} maxLength={120} />
            <label>公司描述</label>
            <textarea value={editDesc} onChange={(e) => setEditDesc(e.target.value)} maxLength={500} placeholder="这家虚拟公司是做什么的…" />
            <div className="modal-actions">
              <button type="button" className="btn-ghost2" onClick={() => setEditing(null)}>取消</button>
              <button type="submit" className="btn-primary" disabled={!editName.trim()}>保存</button>
            </div>
          </form>
        </Modal>
      )}

      {deleting && (
        <Modal title="删除公司" onClose={() => setDeleting(null)}>
          <p className="modal-desc">
            确定删除「{deleting.name}」？该公司下的角色、Agent、记忆将一并删除，且<strong>不可恢复</strong>。
          </p>
          <div className="modal-actions">
            <button type="button" className="btn-ghost2" onClick={() => setDeleting(null)}>取消</button>
            <button type="button" className="btn-danger" onClick={confirmDelete}>删除</button>
          </div>
        </Modal>
      )}
    </>
  );
}
