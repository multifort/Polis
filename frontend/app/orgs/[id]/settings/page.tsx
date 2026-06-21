"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { api, getAccess, type ApiError, type ModelCatalogItem } from "@/lib/api";

export default function OrgSettingsPage() {
  const router = useRouter();
  const params = useParams<{ id: string }>();
  const orgId = params.id;

  const [models, setModels] = useState<ModelCatalogItem[]>([]);
  const [modelId, setModelId] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");

  useEffect(() => {
    if (!getAccess()) {
      router.replace("/");
      return;
    }
    (async () => {
      try {
        const all = await api.listModels();
        // 只列可配置 Key 的文本生成模型（embedding 走本地，无需 Key）
        const chat = all.filter((m) => (m.capabilities ?? []).includes("text-gen"));
        setModels(chat);
        if (chat[0]) setModelId(chat[0].id);
      } catch (e) {
        setErr(e instanceof Error ? e.message : "加载模型目录失败");
      }
    })();
  }, [router]);

  const onSave = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();
      if (!modelId || !apiKey.trim()) return;
      setSaving(true);
      setMsg("");
      setErr("");
      try {
        await api.configureCredential(orgId, modelId, apiKey.trim());
        setMsg(`已保存「${modelId}」的密钥（信封加密存储，明文不入库）`);
        setApiKey("");
      } catch (e2) {
        const status = (e2 as ApiError).status;
        setErr(
          status === 403
            ? "仅公司所有者可配置模型密钥"
            : e2 instanceof Error
              ? e2.message
              : "保存失败",
        );
      } finally {
        setSaving(false);
      }
    },
    [orgId, modelId, apiKey],
  );

  return (
    <>
      <div className="topbar">
        <div className="brand">
          <div className="logo">A</div>
          <span className="brand-name">Polis</span>
        </div>
        <Link className="back" href={`/orgs/${orgId}`}>
          ← 返回公司
        </Link>
      </div>

      <div className="container">
        <div className="page-head">
          <div>
            <h1 className="page-title">模型配置</h1>
            <p className="muted">
              为公司配置大模型密钥（BYO-Key，信封加密存储）。Agent 运行时按需短时注入，用完即焚。
            </p>
          </div>
        </div>

        {err && <p className="error">{err}</p>}
        {msg && <p className="notice">{msg}</p>}

        <div className="wizard">
          <h3>
            <span className="dot" />
            配置聊天模型密钥
          </h3>
          <form className="provision" onSubmit={onSave} style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
            <select value={modelId} onChange={(e) => setModelId(e.target.value)}>
              {models.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.id}
                  {m.provider ? ` (${m.provider})` : ""}
                </option>
              ))}
            </select>
            <input
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder="API Key（如 sk-…）"
              autoComplete="off"
            />
            <button className="btn-primary" type="submit" disabled={saving || !modelId}>
              {saving ? "保存中…" : "保存密钥"}
            </button>
          </form>
          <p className="hint">
            embedding 模型走本地服务（无需密钥）。当前为「单模型」配置；多模型 / 主模型 / 按 Agent 选模型为后续版本。
          </p>
        </div>
      </div>
    </>
  );
}
