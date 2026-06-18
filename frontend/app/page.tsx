"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { api, setTokens } from "@/lib/api";

export default function AuthPage() {
  const router = useRouter();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      const tokens =
        mode === "login"
          ? await api.login({ email, password })
          : await api.register({ email, password, display_name: displayName || undefined });
      setTokens(tokens.access_token, tokens.refresh_token);
      router.push("/dashboard");
    } catch (err) {
      setError(err instanceof Error ? err.message : "操作失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="center">
      <form className="card" onSubmit={submit}>
        <div className="brand">
          <div className="logo">A</div>
          <span className="brand-name">Polis</span>
        </div>
        <p className="subtitle">
          {mode === "login" ? "登录你的城邦工作台" : "创建账号，开启你的第一座城邦"}
        </p>

        {error && <p className="error">{error}</p>}

        {mode === "register" && (
          <div className="field">
            <label>昵称（可选）</label>
            <input value={displayName} onChange={(e) => setDisplayName(e.target.value)} placeholder="如：李工" />
          </div>
        )}
        <div className="field">
          <label>邮箱</label>
          <input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@example.com" />
        </div>
        <div className="field">
          <label>密码{mode === "register" ? "（至少 8 位）" : ""}</label>
          <input type="password" required minLength={mode === "register" ? 8 : undefined} value={password} onChange={(e) => setPassword(e.target.value)} placeholder="••••••••" />
        </div>

        <button className="btn-primary" type="submit" disabled={busy}>
          {busy ? "处理中…" : mode === "login" ? "登录" : "注册并进入"}
        </button>

        <div className="switch">
          {mode === "login" ? "还没有账号？" : "已有账号？"}
          <button type="button" className="link-btn" onClick={() => { setMode(mode === "login" ? "register" : "login"); setError(""); }}>
            {mode === "login" ? "去注册" : "去登录"}
          </button>
        </div>
      </form>
    </div>
  );
}
