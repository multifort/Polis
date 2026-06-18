// Polis 前端 API 客户端：基址 + token 存取 + 请求封装。
const BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

const ACCESS = "polis_access";
const REFRESH = "polis_refresh";

export function setTokens(access: string, refresh: string) {
  localStorage.setItem(ACCESS, access);
  localStorage.setItem(REFRESH, refresh);
}
export function clearTokens() {
  localStorage.removeItem(ACCESS);
  localStorage.removeItem(REFRESH);
}
export function getAccess(): string | null {
  return typeof window === "undefined" ? null : localStorage.getItem(ACCESS);
}

async function request<T>(
  path: string,
  options: RequestInit = {},
  auth = false,
  orgId?: string,
): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (auth) {
    const token = getAccess();
    if (token) headers["Authorization"] = `Bearer ${token}`;
  }
  if (orgId) headers["X-Org-Id"] = orgId;
  const res = await fetch(`${BASE}${path}`, { ...options, headers });
  const data = res.status === 204 ? null : await res.json().catch(() => null);
  if (!res.ok) {
    const detail = (data && (data as { detail?: string }).detail) || `请求失败 (${res.status})`;
    throw new Error(detail);
  }
  return data as T;
}

export interface Tokens {
  access_token: string;
  refresh_token: string;
}
export interface Org {
  id: string;
  name: string;
  role: string;
}
export interface Me {
  user: { id: string; email: string; display_name: string | null };
  orgs: Org[];
}
export interface Preset {
  name: string;
  version: string;
  description: string | null;
  required_capabilities: string[] | null;
}
export interface Agent {
  id: string;
  name: string;
  status: string;
  source: string;
  current_version: string | null;
}
export interface Role {
  id: string;
  name: string;
  description: string | null;
}
export interface ProvisionedAgent {
  name: string;
  role_name: string;
  status: string;
  capabilities: string[];
}
export interface ProvisionResult {
  org: Org;
  preset: string;
  agents: ProvisionedAgent[];
}

export const api = {
  register: (body: { email: string; password: string; display_name?: string }) =>
    request<Tokens>("/api/auth/register", { method: "POST", body: JSON.stringify(body) }),
  login: (body: { email: string; password: string }) =>
    request<Tokens>("/api/auth/login", { method: "POST", body: JSON.stringify(body) }),
  me: () => request<Me>("/api/me", {}, true),
  createOrg: (body: { name: string; charter?: string }) =>
    request<Org>("/api/orgs", { method: "POST", body: JSON.stringify(body) }, true),
  listPresets: () => request<Preset[]>("/api/catalog/presets"),
  provision: (body: { name: string; preset?: string; keyword?: string }) =>
    request<ProvisionResult>("/api/provision", { method: "POST", body: JSON.stringify(body) }, true),
  agents: (orgId: string) => request<Agent[]>("/api/orgs/current/agents", {}, true, orgId),
  roles: (orgId: string) => request<Role[]>("/api/orgs/current/roles", {}, true, orgId),
};
