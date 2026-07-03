"use client";

// C0-1 应用壳：左导航（公司切换 + 工作台/工作/花名册/设置 + 其他公司 + 用户）+ 顶栏 + 全宽主区。
// 布局硬约束（用户反馈）：右侧主区**全宽自适应铺满**，禁止右侧大量留白。
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { api, clearTokens, getAccess, type Me } from "@/lib/api";

type NavKey = "home" | "work" | "scenarios" | "dashboard" | "roster" | "settings";

const NAV: { key: NavKey; label: string; href: (id: string) => string; icon: JSX.Element }[] = [
  { key: "home", label: "工作台", href: (id) => `/orgs/${id}`, icon: <IconHome /> },
  { key: "work", label: "工作", href: (id) => `/orgs/${id}/tasks`, icon: <IconWork /> },
  { key: "scenarios", label: "场景库", href: (id) => `/orgs/${id}/scenarios`, icon: <IconScenarios /> },
  { key: "dashboard", label: "看板", href: (id) => `/orgs/${id}/dashboard`, icon: <IconChart /> },
  { key: "roster", label: "花名册", href: (id) => `/orgs/${id}/roster`, icon: <IconRoster /> },
  { key: "settings", label: "设置", href: (id) => `/orgs/${id}/settings`, icon: <IconGear /> },
];

export default function AppShell({
  orgId,
  active,
  breadcrumb,
  children,
  workBadge,
}: {
  orgId: string;
  active: NavKey;
  breadcrumb?: string;
  children: React.ReactNode;
  workBadge?: number;
}) {
  const router = useRouter();
  const [me, setMe] = useState<Me | null>(null);

  useEffect(() => {
    if (!getAccess()) {
      router.replace("/");
      return;
    }
    api.me().then(setMe).catch(() => undefined);
  }, [router]);

  const org = me?.orgs.find((o) => o.id === orgId) ?? null;
  const others = (me?.orgs ?? []).filter((o) => o.id !== orgId);
  const initial = (org?.name ?? "公").slice(0, 1);
  const userName = me?.user.display_name || me?.user.email?.split("@")[0] || "用户";

  function logout() {
    api.logout().finally(() => {
      clearTokens();
      router.replace("/");
    });
  }

  return (
    <div className="shell">
      <aside className="shell-nav">
        <div className="shell-brand">
          <div className="logo">A</div>
          <span className="brand-name">Polis</span>
        </div>

        <Link className="shell-org" href={`/orgs/${orgId}`} title={org?.name}>
          <span className="shell-org-badge">{initial}</span>
          <span className="shell-org-name">{org?.name ?? "公司"}</span>
          <span className="shell-org-caret">⌄</span>
        </Link>

        <nav className="shell-menu">
          {NAV.map((n) => (
            <Link
              key={n.key}
              href={n.href(orgId)}
              className={`shell-item${active === n.key ? " active" : ""}`}
            >
              <span className="shell-ico">{n.icon}</span>
              <span>{n.label}</span>
              {n.key === "work" && workBadge ? (
                <span className="shell-badge">{workBadge}</span>
              ) : null}
            </Link>
          ))}
        </nav>

        {others.length > 0 && (
          <div className="shell-others">
            <div className="shell-others-title">其他公司</div>
            {others.map((o) => (
              <button
                key={o.id}
                className="shell-other"
                onClick={() => router.push(`/orgs/${o.id}`)}
              >
                <span className="dot" />
                <span>{o.name}</span>
              </button>
            ))}
          </div>
        )}

        <div className="shell-user">
          <span className="shell-avatar">{userName.slice(0, 1)}</span>
          <div className="shell-user-meta">
            <div className="shell-user-name">{userName}</div>
            <div className="shell-user-role">{org?.role === "owner" ? "所有者" : "成员"}</div>
          </div>
          <button className="shell-logout" onClick={logout} title="退出登录">
            ⏻
          </button>
        </div>
      </aside>

      <div className="shell-main">
        <header className="shell-top">
          <div className="shell-crumb">
            <span className="muted">{org?.name ?? "公司"}</span>
            <span className="sep">›</span>
            <span className="cur">{breadcrumb ?? "工作台"}</span>
          </div>
          <div className="shell-top-actions">
            {active === "home" && (
              <Link className="btn-primary" href="/dashboard">
                ＋ 新建公司
              </Link>
            )}
          </div>
        </header>
        <main className="shell-content">{children}</main>
      </div>
    </div>
  );
}

function IconHome() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M3 11l9-8 9 8" /><path d="M5 10v10h14V10" />
    </svg>
  );
}
function IconWork() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <rect x="3" y="7" width="18" height="13" rx="2" /><path d="M8 7V5a2 2 0 012-2h4a2 2 0 012 2v2" />
    </svg>
  );
}
function IconScenarios() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <rect x="4" y="4" width="7" height="7" rx="1.5" />
      <rect x="13" y="4" width="7" height="7" rx="1.5" />
      <rect x="4" y="13" width="7" height="7" rx="1.5" />
      <path d="M13 17h7" /><path d="M16.5 13.5v7" />
    </svg>
  );
}
function IconRoster() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <circle cx="9" cy="8" r="3" /><path d="M3 20c0-3 3-5 6-5s6 2 6 5" /><path d="M17 7a3 3 0 010 6" />
    </svg>
  );
}
function IconChart() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M4 20V10" /><path d="M12 20V4" /><path d="M20 20v-7" />
    </svg>
  );
}
function IconGear() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <circle cx="12" cy="12" r="3" />
      <path d="M19 12a7 7 0 00-.1-1l2-1.5-2-3.4-2.3 1a7 7 0 00-1.7-1l-.3-2.6h-4l-.3 2.6a7 7 0 00-1.7 1l-2.3-1-2 3.4 2 1.5a7 7 0 000 2l-2 1.5 2 3.4 2.3-1a7 7 0 001.7 1l.3 2.6h4l.3-2.6a7 7 0 001.7-1l2.3 1 2-3.4-2-1.5a7 7 0 00.1-1z" />
    </svg>
  );
}
