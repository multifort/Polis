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
    const d = data && (data as { detail?: unknown }).detail;
    let detail: string;
    if (d && typeof d === "object" && Array.isArray((d as { errors?: unknown[] }).errors)) {
      detail = (d as { errors: string[] }).errors.join("；");
    } else {
      detail = (typeof d === "string" && d) || `请求失败 (${res.status})`;
    }
    const err = new Error(detail) as ApiError;
    err.status = res.status;
    throw err;
  }
  return data as T;
}

export interface ApiError extends Error {
  status?: number;
}

export interface Tokens {
  access_token: string;
  refresh_token: string;
}
export interface Org {
  id: string;
  name: string;
  role: string;
  description?: string | null;
}
export interface Member {
  user_id: string;
  email: string;
  display_name: string | null;
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

// ── 计划 / 运行（M3） ──────────────────────────────────────────────
export interface PlanNode {
  id: string;
  type: "agent" | "skill" | "human" | "workflow" | "system";
  deps: string[];
  required_capabilities: string[];
  executor: string;
  input_hint?: string | null;
  expected_output?: string | null;
  dangerous: boolean;
}
export interface PlanDag {
  workflow_name: string;
  goal: string;
  acceptance_criteria?: string | null;
  budget_cents: number;
  nodes: PlanNode[];
}
export interface PlanResult {
  id: string;
  goal: string;
  status: string;
  template: string;
  estimated_cost_cents: number;
  dag: PlanDag;
  routing: Record<string, string | null>;
}
export interface ApproveResult {
  task_id: string;
  status: string;
}
export interface RunNodeState {
  id: string;
  status: string;
  agent?: string | null;
}
export interface RunStatus {
  status: string;
  nodes: RunNodeState[];
}

export const api = {
  register: (body: { email: string; password: string; display_name?: string }) =>
    request<Tokens>("/api/auth/register", { method: "POST", body: JSON.stringify(body) }),
  login: (body: { email: string; password: string }) =>
    request<Tokens>("/api/auth/login", { method: "POST", body: JSON.stringify(body) }),
  me: () => request<Me>("/api/me", {}, true),
  createOrg: (body: { name: string; charter?: string }) =>
    request<Org>("/api/orgs", { method: "POST", body: JSON.stringify(body) }, true),
  updateOrg: (id: string, name: string, description: string | null) =>
    request<Org>(
      `/api/orgs/${id}`,
      { method: "PATCH", body: JSON.stringify({ name, description }) },
      true,
    ),
  deleteOrg: (id: string) => request<null>(`/api/orgs/${id}`, { method: "DELETE" }, true),
  members: (id: string) => request<Member[]>(`/api/orgs/${id}/members`, {}, true),
  listPresets: () => request<Preset[]>("/api/catalog/presets"),
  provision: (body: { name: string; description?: string; preset?: string; keyword?: string }) =>
    request<ProvisionResult>("/api/provision", { method: "POST", body: JSON.stringify(body) }, true),
  agents: (orgId: string) => request<Agent[]>("/api/orgs/current/agents", {}, true, orgId),
  roles: (orgId: string) => request<Role[]>("/api/orgs/current/roles", {}, true, orgId),
  createPlan: (orgId: string, goal: string) =>
    request<PlanResult>("/api/plans", { method: "POST", body: JSON.stringify({ goal }) }, true, orgId),
  approvePlan: (orgId: string, planId: string) =>
    request<ApproveResult>(`/api/plans/${planId}/approve`, { method: "POST" }, true, orgId),
  planRun: (orgId: string, planId: string) =>
    request<RunStatus>(`/api/plans/${planId}/run`, {}, true, orgId),
  signalNode: (orgId: string, planId: string, nodeId: string) =>
    request<null>(
      `/api/plans/${planId}/signal`,
      { method: "POST", body: JSON.stringify({ node_id: nodeId }) },
      true,
      orgId,
    ),
};
