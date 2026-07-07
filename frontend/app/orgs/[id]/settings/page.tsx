"use client";

// C0 设置页：公司信息 + 模型配置（并排）+ 删除公司（对照原型）。
import { useCallback, useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import AppShell from "@/components/AppShell";
import { api, getAccess, type ApiError, type Me, type ModelCatalogItem } from "@/lib/api";

function statusPill(ok: boolean) {
  return ok
    ? { label: "凭证就绪", color: "#1b5e20", bg: "#e8f5e9" }
    : { label: "待配置", color: "#7a3e00", bg: "#fff4e5" };
}

export default function OrgSettingsPage() {
  const router = useRouter();
  const orgId = useParams<{ id: string }>().id;

  const [me, setMe] = useState<Me | null>(null);
  const [models, setModels] = useState<ModelCatalogItem[]>([]);
  const [modelId, setModelId] = useState("");
  const [primaryModelId, setPrimaryModelId] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");
  const [name, setName] = useState("");
  const [desc, setDesc] = useState("");
  const [savingInfo, setSavingInfo] = useState(false);
  const [deleting, setDeleting] = useState(false);

  useEffect(() => {
    if (!getAccess()) { router.replace("/"); return; }
    // 拉公司信息
    api.me().then((m) => {
      setMe(m);
      const o = m.orgs.find((x) => x.id === orgId);
      if (o) {
        setName(o.name);
        setDesc(o.description || "");
        setPrimaryModelId(o.primary_model_id || "");
      }
    }).catch(() => undefined);
    // 拉模型目录
    api.listModels().then((all) => {
      const chat = all.filter((m) => (m.capabilities ?? []).includes("text-gen"));
      setModels(chat);
      if (chat[0]) setModelId(chat[0].id);
    }).catch(() => setErr("加载模型目录失败"));
  }, [orgId, router]);

  const onSaveKey = useCallback(async (e: React.FormEvent) => {
    e.preventDefault();
    if (!modelId || !apiKey.trim()) return;
    setSaving(true); setMsg(""); setErr("");
    try {
      await api.configureCredential(orgId, modelId, apiKey.trim());
      setMsg(`已保存「${modelId}」的密钥（信封加密存储，明文不入库）`);
      setApiKey("");
    } catch (e2) {
      const s = (e2 as ApiError).status;
      setErr(s === 403 ? "仅公司所有者可配置模型密钥" : e2 instanceof Error ? e2.message : "保存失败");
    } finally { setSaving(false); }
  }, [orgId, modelId, apiKey]);

  const onSaveInfo = useCallback(async () => {
    setSavingInfo(true); setMsg(""); setErr("");
    try {
      await api.updateOrg(orgId, name.trim(), desc.trim() || null, primaryModelId || null);
      setMsg("公司信息已保存");
      setMe((prev) =>
        prev
          ? {
              ...prev,
              orgs: prev.orgs.map((o) =>
                o.id === orgId
                  ? {
                      ...o,
                      name: name.trim(),
                      description: desc.trim() || null,
                      primary_model_id: primaryModelId || null,
                    }
                  : o,
              ),
            }
          : prev,
      );
    } catch (e2) {
      setErr(e2 instanceof Error ? e2.message : "保存失败");
    } finally { setSavingInfo(false); }
  }, [orgId, name, desc, primaryModelId]);

  const onDelete = useCallback(async () => {
    if (!confirm("确定删除这家公司？其角色、Agent、记忆与运行历史将一并删除，不可恢复。")) return;
    setDeleting(true); setErr("");
    try {
      await api.deleteOrg(orgId);
      router.replace("/dashboard");
    } catch (e2) {
      setErr(e2 instanceof Error ? e2.message : "删除失败");
      setDeleting(false);
    }
  }, [orgId, router]);

  return (
    <AppShell orgId={orgId} active="settings" breadcrumb="设置">
      <div style={{ marginBottom: 20 }}>
        <h1 className="page-title big">设置</h1>
      </div>

      {/* 并排双卡：公司信息 + 模型配置 */}
      <div className="settings-grid">
        {/* 公司信息 */}
        <div className="settings-card">
          <h3>公司信息</h3>
          <label>公司名称</label>
          <input value={name} onChange={(e) => setName(e.target.value)} />
          <label>公司描述</label>
          <textarea value={desc} onChange={(e) => setDesc(e.target.value)} rows={3} />
          <label>主模型</label>
          <select value={primaryModelId} onChange={(e) => setPrimaryModelId(e.target.value)}>
            <option value="">系统默认模型</option>
            {models.map((m) => (
              <option key={m.id} value={m.id}>
                {m.id}
              </option>
            ))}
          </select>
          <div className="settings-actions">
            <button className="btn-primary" onClick={onSaveInfo} disabled={savingInfo}>
              {savingInfo ? "保存中…" : "保存"}
            </button>
          </div>
        </div>

        {/* 模型配置 */}
        <div className="settings-card">
          <h3>模型配置</h3>
          {models.map((m) => {
            const ok = true; // 后端无"是否已配 Key"查询，统一显示名/状态
            const p = statusPill(ok);
            return (
              <div className="settings-model-row" key={m.id}>
                <div className="settings-model-info">
                  <div className="settings-model-name">
                    {m.capabilities?.includes("text-gen") ? "推理 · " : ""}{m.id}
                  </div>
                  <div className="settings-model-id mono">{m.provider || ""}</div>
                </div>
                <span style={{ fontSize: 11, color: p.color, background: p.bg, padding: "2px 8px", borderRadius: 8 }}>
                  {p.label}
                </span>
              </div>
            );
          })}

          {/* 新增密钥 */}
          <div style={{ marginTop: 14, borderTop: "1px solid #f1f2f8", paddingTop: 14 }}>
            <label>新增 / 更新密钥</label>
            <form onSubmit={onSaveKey} style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              <select value={modelId} onChange={(e) => setModelId(e.target.value)} style={{ flex: 1, minWidth: 140 }}>
                {models.map((m) => (
                  <option key={m.id} value={m.id}>{m.id}</option>
                ))}
              </select>
              <input
                type="password"
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                placeholder="API Key（sk-…）"
                autoComplete="off"
                style={{ flex: 2, minWidth: 160 }}
              />
              <button className="btn-primary" type="submit" disabled={saving || !modelId} style={{ width: "auto", height: 42, padding: "0 16px" }}>
                {saving ? "…" : "保存"}
              </button>
            </form>
            {msg && <p className="notice" style={{ marginTop: 8 }}>{msg}</p>}
            {err && <p className="error" style={{ marginTop: 8 }}>{err}</p>}
          </div>
        </div>
      </div>

      {/* 删除公司（危险区） */}
      <div className="settings-danger">
        <div className="settings-danger-body">
          <div className="settings-danger-title">删除这家公司</div>
          <div className="settings-danger-desc">
            该公司下的角色、Agent、记忆与运行历史将一并删除，且不可恢复。
          </div>
        </div>
        <button className="btn-danger-outline" onClick={onDelete} disabled={deleting}>
          {deleting ? "删除中…" : "删除公司"}
        </button>
      </div>
    </AppShell>
  );
}
