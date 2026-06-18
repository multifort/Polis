"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { api, setTokens } from "@/lib/api";

function HeroArt() {
  return (
    <svg viewBox="0 0 480 340" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Polis 工作台示意">
      <ellipse cx="240" cy="300" rx="190" ry="26" fill="#3f51b5" opacity="0.07" />
      {/* 主卡片 */}
      <g>
        <rect x="130" y="70" width="220" height="160" rx="14" fill="#ffffff" stroke="#e0e3f5" />
        <rect x="130" y="70" width="220" height="34" rx="14" fill="#3f51b5" />
        <rect x="130" y="92" width="220" height="12" fill="#3f51b5" />
        <circle cx="148" cy="87" r="4" fill="#ffffff" opacity="0.8" />
        <circle cx="162" cy="87" r="4" fill="#ffffff" opacity="0.55" />
        <circle cx="176" cy="87" r="4" fill="#ffffff" opacity="0.4" />
        {/* 折线图 */}
        <polyline points="150,200 185,175 215,188 250,150 285,162 320,128" fill="none" stroke="#3f51b5" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
        <circle cx="250" cy="150" r="4" fill="#757de8" />
        <circle cx="320" cy="128" r="4" fill="#757de8" />
        <rect x="150" y="120" width="80" height="9" rx="4" fill="#e8eaf6" />
        <rect x="150" y="135" width="54" height="9" rx="4" fill="#eef0fb" />
      </g>
      {/* 左上小卡（环形） */}
      <g>
        <rect x="60" y="120" width="92" height="78" rx="12" fill="#ffffff" stroke="#e0e3f5" />
        <circle cx="106" cy="158" r="22" fill="none" stroke="#e8eaf6" strokeWidth="7" />
        <circle cx="106" cy="158" r="22" fill="none" stroke="#3f51b5" strokeWidth="7" strokeDasharray="90 140" strokeLinecap="round" transform="rotate(-90 106 158)" />
        <rect x="78" y="186" width="56" height="6" rx="3" fill="#eef0fb" />
      </g>
      {/* 右侧小卡（柱状） */}
      <g>
        <rect x="330" y="150" width="92" height="84" rx="12" fill="#ffffff" stroke="#e0e3f5" />
        <rect x="344" y="200" width="12" height="22" rx="3" fill="#757de8" />
        <rect x="362" y="186" width="12" height="36" rx="3" fill="#3f51b5" />
        <rect x="380" y="194" width="12" height="28" rx="3" fill="#9fa8e8" />
        <rect x="398" y="178" width="12" height="44" rx="3" fill="#3f51b5" />
        <rect x="344" y="166" width="48" height="6" rx="3" fill="#eef0fb" />
      </g>
      {/* 盾牌 + 头像 */}
      <g>
        <path d="M250 44 l26 9 v18 c0 16 -11 26 -26 31 c-15 -5 -26 -15 -26 -31 v-18 z" fill="#e8eaf6" stroke="#3f51b5" strokeWidth="2" />
        <path d="M240 76 l7 7 l14 -15" fill="none" stroke="#3f51b5" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
      </g>
      <circle cx="96" cy="96" r="16" fill="#757de8" />
      <circle cx="96" cy="90" r="6" fill="#ffffff" />
      <path d="M85 104 a11 9 0 0 1 22 0 z" fill="#ffffff" />
    </svg>
  );
}

const FEATURES = [
  { icon: "shield", title: "安全可靠", sub: "多重安全保障", bg: "#e8eaf6", fg: "#3f51b5" },
  { icon: "bolt", title: "高效协作", sub: "提升团队效率", bg: "#e8f5e9", fg: "#2e7d32" },
  { icon: "layers", title: "开放集成", sub: "灵活扩展能力", bg: "#ede7f6", fg: "#7e57c2" },
];

function FeatureIcon({ name }: { name: string }) {
  const common = { width: 18, height: 18, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 2, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };
  if (name === "shield")
    return <svg {...common}><path d="M12 3l7 3v5c0 5-3.5 8-7 9-3.5-1-7-4-7-9V6z" /><path d="M9 12l2 2 4-4" /></svg>;
  if (name === "bolt")
    return <svg {...common}><path d="M13 2L4 14h7l-1 8 9-12h-7z" /></svg>;
  return <svg {...common}><path d="M12 3l9 5-9 5-9-5z" /><path d="M3 13l9 5 9-5" /></svg>;
}

export default function AuthPage() {
  const router = useRouter();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [showPwd, setShowPwd] = useState(false);
  const [remember, setRemember] = useState(true);
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
    <div className="auth-wrap">
      <div className="auth-grid">
        <section className="hero">
          <div className="hero-brand">
            <div className="logo">A</div>
            <div>
              <div className="brand-name">Polis</div>
              <div className="brand-tag">虚拟智能企业平台</div>
            </div>
          </div>
          <h1>
            欢迎使用 <span className="accent">Polis</span> 工作台
          </h1>
          <div className="hero-rule" />
          <p className="hero-sub">你的「虚拟智能企业」平台 —— 一个目标，开出一家 AI 虚拟公司。</p>
          <p className="hero-sub">角色化智能体替你规划、协作、交付，全程可控、可审计。</p>
          <div className="hero-illu">
            <HeroArt />
          </div>
          <div className="features">
            {FEATURES.map((f) => (
              <div className="feature" key={f.title}>
                <div className="tile" style={{ background: f.bg, color: f.fg }}>
                  <FeatureIcon name={f.icon} />
                </div>
                <div>
                  <div className="ft">{f.title}</div>
                  <div className="fs">{f.sub}</div>
                </div>
              </div>
            ))}
          </div>
        </section>

        <section className="auth-card-col">
          <form className="auth-card" onSubmit={submit}>
            <div className="brand">
              <div className="logo sm">A</div>
              <span className="brand-name">Polis</span>
            </div>
            <p className="subtitle">
              {mode === "login" ? "登录你的虚拟智能企业工作台" : "创建账号，开启你的第一家虚拟公司"}
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
              <div className="pwd">
              <input
                type={showPwd ? "text" : "password"}
                required
                minLength={mode === "register" ? 8 : undefined}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
              />
              <button type="button" className="eye" aria-label={showPwd ? "隐藏密码" : "显示密码"} onClick={() => setShowPwd(!showPwd)}>
                {showPwd ? (
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M17.94 17.94A10 10 0 0 1 12 20C5 20 1 12 1 12a18 18 0 0 1 5.06-5.94M9.9 4.24A9 9 0 0 1 12 4c7 0 11 8 11 8a18 18 0 0 1-2.16 3.19M1 1l22 22" /></svg>
                ) : (
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" /><circle cx="12" cy="12" r="3" /></svg>
                )}
              </button>
              </div>
            </div>

            {mode === "login" && (
              <div className="row-between">
                <label className="remember">
                  <input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} />
                  记住我
                </label>
                <button type="button" className="link-btn" onClick={() => setError("找回密码功能即将上线")}>
                  忘记密码？
                </button>
              </div>
            )}

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
        </section>
      </div>
    </div>
  );
}
