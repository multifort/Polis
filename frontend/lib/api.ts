// Polis 前端 API 客户端：基址 + token 存取 + 请求封装。
const BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

const ACCESS = "polis_access";
const REFRESH = "polis_refresh";

// 触发浏览器保存一个 blob（导出下载用）。
export function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

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
export function getRefresh(): string | null {
  return typeof window === "undefined" ? null : localStorage.getItem(REFRESH);
}

// 静默刷新（TD-014）：access 过期(401)时用 refresh 换新一对并重试原请求一次。
// 并发请求共享同一次刷新，避免风暴（refresh 轮换后旧 token 立即失效，见后端 TD-012）。
let refreshing: Promise<boolean> | null = null;

async function tryRefresh(): Promise<boolean> {
  if (refreshing) return refreshing;
  refreshing = (async () => {
    const rt = getRefresh();
    if (!rt) return false;
    try {
      const res = await fetch(`${BASE}/api/auth/refresh`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: rt }),
      });
      if (!res.ok) return false;
      const data = (await res.json()) as Tokens;
      setTokens(data.access_token, data.refresh_token);
      return true;
    } catch {
      return false;
    }
  })();
  try {
    return await refreshing;
  } finally {
    refreshing = null;
  }
}

async function request<T>(
  path: string,
  options: RequestInit = {},
  auth = false,
  orgId?: string,
  _retried = false,
): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (auth) {
    const token = getAccess();
    if (token) headers["Authorization"] = `Bearer ${token}`;
  }
  if (orgId) headers["X-Org-Id"] = orgId;
  const res = await fetch(`${BASE}${path}`, { ...options, headers });

  // access 过期：静默刷新后重试一次（refresh 端点自身不参与，避免递归）
  if (res.status === 401 && auth && !_retried && path !== "/api/auth/refresh") {
    if (await tryRefresh()) {
      return request<T>(path, options, auth, orgId, true);
    }
    clearTokens(); // 刷新失败 → 清登录态，页面的 getAccess 守卫会跳回登录
  }

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
export interface PasswordResetRequestResult {
  accepted: boolean;
  reset_token: string | null;
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
export interface ModelCatalogItem {
  id: string;
  provider?: string | null;
  capabilities?: string[] | null;
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
  role?: string | null;
  description?: string | null;
  capabilities?: string[];
  model?: string | null;
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

// ── 运行观测（M6 H-3）──────────────────────────────────────────────
export interface ObsNode {
  node_id: string;
  status: string;
  summary: string | null;
  content: string | null; // 全文（展示用）
  needs_human: boolean;
  created_at: string | null;
  provenance: Record<string, unknown> | null;
}
export interface ObsLLMCall {
  name: string | null;
  model: string | null;
  input: string | null;
  output: string | null;
  input_tokens: number | null;
  output_tokens: number | null;
  total_tokens: number | null;
  cost: number | null;
}
export interface ObsTotals {
  calls: number;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  cost: number;
}
export interface ObsModelUsage {
  model: string;
  calls: number;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  cost: number;
}
// ── 任务实体（V2-P1）──────────────────────────────────────────────
export interface Task {
  id: string;
  name: string;
  goal: string;
  scenario_ref?: string | null;
  priority?: number;
  status: string;
}
export interface TaskRunRow {
  id: string;
  task_id?: string | null;
  plan_id?: string | null;
  status: string;
  priority?: number;
  created_at?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  estimated_cost_cents?: number | null;
  actual_cost?: number | null;
}

// ── P4 看板（跨任务/场景运营统计）─────────────────────────────────────
export interface TemplateDistItem {
  template: string;
  count: number;
  is_template_hit: boolean;
}
export interface DashboardStats {
  total_runs: number;
  by_status: Record<string, number>;
  success_rate: number | null;
  avg_duration_seconds: number | null;
  active_runs: number;
  org_max_concurrent_runs: number;
  reuse_hit_rate: number | null;
  approval_pass_rate: number | null;
  by_template: TemplateDistItem[];
  recent_window: number;
  recent_total_cost: number | null;
  recent_total_tokens: number | null;
  budget_cents: number;
  estimated_cost_cents: number;
}

export interface Observability {
  task_id: string;
  status: string;
  started_at: string | null;
  finished_at: string | null;
  duration_seconds: number | null;
  manifest: {
    plan_version: string | null;
    models_used: Record<string, unknown> | null;
    agents_used: Record<string, unknown> | null;
  } | null;
  nodes: ObsNode[];
  llm_calls: ObsLLMCall[];
  totals: ObsTotals;
  by_model: ObsModelUsage[];
}

export const api = {
  register: (body: { email: string; password: string; display_name?: string }) =>
    request<Tokens>("/api/auth/register", { method: "POST", body: JSON.stringify(body) }),
  login: (body: { email: string; password: string }) =>
    request<Tokens>("/api/auth/login", { method: "POST", body: JSON.stringify(body) }),
  requestPasswordReset: (body: { email: string }) =>
    request<PasswordResetRequestResult>("/api/auth/password/reset/request", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  confirmPasswordReset: (body: { token: string; new_password: string }) =>
    request<null>("/api/auth/password/reset/confirm", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  logout: async () => {
    const rt = getRefresh();
    if (rt) {
      try {
        await request<null>("/api/auth/logout", {
          method: "POST",
          body: JSON.stringify({ refresh_token: rt }),
        });
      } catch {
        // 登出尽力而为：即使后端不可达也清本地态
      }
    }
    clearTokens();
  },
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
  listModels: () => request<ModelCatalogItem[]>("/api/catalog/models"),
  configureCredential: (orgId: string, modelId: string, apiKey: string) =>
    request<{ model_id: string; configured: boolean }>(
      "/api/credentials",
      { method: "POST", body: JSON.stringify({ model_id: modelId, api_key: apiKey }) },
      true,
      orgId,
    ),
  provision: (body: { name: string; description?: string; preset?: string; keyword?: string }) =>
    request<ProvisionResult>("/api/provision", { method: "POST", body: JSON.stringify(body) }, true),
  agents: (orgId: string) => request<Agent[]>("/api/orgs/current/agents", {}, true, orgId),
  roles: (orgId: string) => request<Role[]>("/api/orgs/current/roles", {}, true, orgId),
  createPlan: (orgId: string, goal: string) =>
    request<PlanResult>("/api/plans", { method: "POST", body: JSON.stringify({ goal }) }, true, orgId),
  createTaskPlan: (orgId: string, taskId: string) =>
    request<PlanResult>(`/api/tasks/${taskId}/plan`, { method: "POST" }, true, orgId),
  getPlan: (orgId: string, planId: string) =>
    request<PlanResult>(`/api/plans/${planId}`, {}, true, orgId),
  approvePlan: (orgId: string, planId: string) =>
    request<ApproveResult>(`/api/plans/${planId}/approve`, { method: "POST" }, true, orgId),
  planRun: (orgId: string, planId: string) =>
    request<RunStatus>(`/api/plans/${planId}/run`, {}, true, orgId),
  planObservability: (orgId: string, planId: string) =>
    request<Observability>(`/api/plans/${planId}/observability`, {}, true, orgId),
  signalNode: (orgId: string, planId: string, nodeId: string) =>
    request<null>(
      `/api/plans/${planId}/signal`,
      { method: "POST", body: JSON.stringify({ node_id: nodeId }) },
      true,
      orgId,
    ),
  // 结果导出（V2-P3b）：md/pdf，直接拿文件 blob（非 JSON），触发浏览器下载。
  exportPlan: async (orgId: string, planId: string, fmt: "md" | "pdf"): Promise<Blob> => {
    const token = getAccess();
    const res = await fetch(`${BASE}/api/plans/${planId}/export?fmt=${fmt}`, {
      method: "POST",
      headers: {
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        "X-Org-Id": orgId,
      },
    });
    if (!res.ok) throw new Error(`导出失败（${res.status}）`);
    return res.blob();
  },
  // ── 任务实体（V2-P1）──
  createTask: (
    orgId: string,
    body: {
      name: string;
      goal: string;
      scenario_ref?: string;
      input_schema?: Record<string, unknown>;
      inputs?: Record<string, unknown>;
      priority?: number | null;
    },
  ) =>
    request<Task>("/api/tasks", { method: "POST", body: JSON.stringify(body) }, true, orgId),
  listTasks: (orgId: string) => request<Task[]>("/api/tasks", {}, true, orgId),
  deleteTask: (orgId: string, taskId: string) =>
    request<null>(`/api/tasks/${taskId}`, { method: "DELETE" }, true, orgId),
  runTask: (orgId: string, taskId: string) =>
    request<ApproveResult>(`/api/tasks/${taskId}/run`, { method: "POST" }, true, orgId),
  taskRuns: (orgId: string, taskId: string) =>
    request<TaskRunRow[]>(`/api/tasks/${taskId}/runs`, {}, true, orgId),
  // ── 看板（V2-P4）──
  dashboard: (orgId: string) => request<DashboardStats>("/api/dashboard", {}, true, orgId),
  // ── 审批收件箱（M6-G / 工作台「需要你处理」）──
  listApprovals: (orgId: string, status = "pending") =>
    request<ApprovalRow[]>(`/api/approvals?status=${status}`, {}, true, orgId),
  decideApproval: (orgId: string, approvalId: string, approve: boolean) =>
    request<ApprovalRow>(
      `/api/approvals/${approvalId}/decide`,
      { method: "POST", body: JSON.stringify({ approve }) },
      true,
      orgId,
    ),
  // ── C0-4 工作台 ──
  workspaceRuns: (orgId: string) =>
    request<WorkspaceRuns>("/api/runs/workspace", {}, true, orgId),
  // ── R3 场景模板 ──
  saveAsTemplate: (orgId: string, planId: string, body: { name: string; domain?: string; subcategory?: string }) =>
    request<TemplateOut>(`/api/plans/${planId}/save-as-template`, { method: "POST", body: JSON.stringify(body) }, true, orgId),
  listTemplates: (orgId: string, domain?: string) =>
    request<TemplateOut[]>(`/api/catalog/templates${domain ? `?domain=${encodeURIComponent(domain)}` : ""}`, {}, true, orgId),
  listDomains: (orgId: string) =>
    request<string[]>("/api/catalog/domains", {}, true, orgId),
  listCategories: (orgId: string, domain?: string) =>
    request<SceneCategoryOut[]>(`/api/catalog/categories${domain ? `?domain=${encodeURIComponent(domain)}` : ""}`, {}, true, orgId),
  createCategory: (orgId: string, body: { domain: string; subcategory?: string | null }) =>
    request<SceneCategoryOut>("/api/catalog/categories", { method: "POST", body: JSON.stringify(body) }, true, orgId),
  updateCategory: (orgId: string, categoryId: string, body: { domain: string; subcategory?: string | null }) =>
    request<SceneCategoryOut>(`/api/catalog/categories/${categoryId}`, { method: "PATCH", body: JSON.stringify(body) }, true, orgId),
  deleteCategory: (orgId: string, categoryId: string) =>
    request<null>(`/api/catalog/categories/${categoryId}`, { method: "DELETE" }, true, orgId),
};

export interface ApprovalRow {
  id: string;
  kind: string;
  ref_id: string | null;
  payload: Record<string, unknown> | null;
  status: string;
}

// ── C0-4 工作台 workspace runs ─────────────────────────────────────────
export interface WorkspaceRunItem {
  run_id: string;
  task_id: string | null;
  task_name: string | null;
  task_goal: string | null;
  plan_id: string | null;
  run_status: string;
  started_at: string | null;
  finished_at: string | null;
  node_count: number;
  estimated_cost_cents: number | null;
  actual_cost: number | null;
}
export interface WorkspaceRuns {
  active: WorkspaceRunItem[];
  recent: WorkspaceRunItem[];
}

// ── R3 场景模板 ──
export interface TemplateOut {
  id: string;
  name: string;
  version: string;
  domain?: string | null;
  subcategory?: string | null;
  source: string;
  visibility: string;
}

export interface SceneCategoryOut {
  id: string;
  domain: string;
  subcategory?: string | null;
  org_id?: string | null;
}
