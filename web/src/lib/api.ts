import type {
  ApprovalItem,
  AuditEvent,
  CursorPage,
  DefinitionDiff,
  Decision,
  Overview,
  Page,
  Policy,
  PolicyDecision,
  PrincipalInfo,
  ScanReport,
  ToolDetail,
  ToolStatus,
  ToolSummary,
  Upstream,
} from "@/lib/types";

const BASE = "/api/gateway";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly detail: string,
    readonly extra?: Record<string, unknown>,
  ) {
    super(detail);
    this.name = "ApiError";
  }
}

export function signIn(): void {
  const returnTo = `${window.location.pathname}${window.location.search}`;
  window.location.assign(`/api/auth/login?returnTo=${encodeURIComponent(returnTo)}`);
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });
  if (response.status === 401 && typeof window !== "undefined") {
    signIn();
  }
  if (!response.ok) {
    let detail = response.statusText;
    let extra: Record<string, unknown> | undefined;
    try {
      const body = (await response.json()) as Record<string, unknown>;
      detail = typeof body.detail === "string" ? body.detail : detail;
      extra = body;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(response.status, detail, extra);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export interface ToolQuery {
  status?: ToolStatus;
  upstream_id?: string;
  risk?: string;
  q?: string;
  include_removed?: boolean;
  limit?: number;
  offset?: number;
}

function qs(params: Record<string, string | number | boolean | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== "") search.set(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}

export const api = {
  overview: () => request<Overview>("/v1/overview"),
  upstreams: () => request<Upstream[]>("/v1/upstreams"),
  createUpstream: (body: unknown) =>
    request<Upstream>("/v1/upstreams", { method: "POST", body: JSON.stringify(body) }),
  updateUpstream: (id: string, body: unknown) =>
    request<Upstream>(`/v1/upstreams/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  deleteUpstream: (id: string) => request<void>(`/v1/upstreams/${id}`, { method: "DELETE" }),
  syncUpstream: (id: string) => request<unknown>(`/v1/upstreams/${id}/sync`, { method: "POST" }),

  tools: (query: ToolQuery = {}) => request<Page<ToolSummary>>(`/v1/tools${qs({ ...query })}`),
  tool: (id: string) => request<ToolDetail>(`/v1/tools/${id}`),
  toolDiff: (id: string) => request<DefinitionDiff>(`/v1/tools/${id}/diff`),
  approveTool: (id: string, expected_hash: string, note: string) =>
    request<ToolSummary>(`/v1/tools/${id}/approve`, {
      method: "POST",
      body: JSON.stringify({ expected_hash, note }),
    }),
  rejectTool: (id: string, reason: string) =>
    request<ToolSummary>(`/v1/tools/${id}/reject`, { method: "POST", body: JSON.stringify({ reason }) }),
  rescanTool: (id: string) => request<ScanReport>(`/v1/tools/${id}/rescan`, { method: "POST" }),
  approvals: () => request<ApprovalItem[]>("/v1/approvals"),

  policies: () => request<Policy[]>("/v1/policies"),
  createPolicy: (body: unknown) =>
    request<Policy>("/v1/policies", { method: "POST", body: JSON.stringify(body) }),
  updatePolicy: (id: string, body: unknown) =>
    request<Policy>(`/v1/policies/${id}`, { method: "PUT", body: JSON.stringify(body) }),
  deletePolicy: (id: string) => request<void>(`/v1/policies/${id}`, { method: "DELETE" }),
  simulate: (body: unknown) =>
    request<PolicyDecision>("/v1/policies/simulate", { method: "POST", body: JSON.stringify(body) }),

  audit: (params: AuditQuery & { cursor?: string; limit?: number } = {}) =>
    request<CursorPage<AuditEvent>>(`/v1/audit${qs({ ...params })}`),

  principals: () => request<PrincipalInfo[]>("/v1/principals"),
};

export interface AuditQuery {
  decision?: Decision;
  tool?: string;
  principal?: string;
}

export interface ConsoleSession {
  subject: string;
}

export async function fetchSession(): Promise<ConsoleSession | null> {
  const response = await fetch("/api/auth/session", { cache: "no-store" });
  if (!response.ok) return null;
  return (await response.json()) as ConsoleSession;
}

export async function signOut(): Promise<void> {
  const response = await fetch("/api/auth/logout", { method: "POST" });
  const body = (await response.json().catch(() => null)) as { next?: unknown } | null;
  window.location.assign(typeof body?.next === "string" ? body.next : "/signed-out");
}
