import type {
  AssistRequest,
  ToolResponse,
  Ticket,
  ReturnApplication,
  Metrics,
  TraceData,
  ObservabilitySummary,
  MemoryListResponse,
  ResolveTicketRequest,
  ReviewReturnRequest,
} from "../types/api";

const API_ORIGIN =
  typeof window !== "undefined" && window.location.protocol === "file:"
    ? "http://127.0.0.1:8000"
    : "";

function apiUrl(path: string): string {
  return `${API_ORIGIN}${path}`;
}

async function postJson<T>(path: string, body: unknown, headers: Record<string, string> = {}): Promise<T> {
  const res = await fetch(apiUrl(path), {
    method: "POST",
    headers: { "Content-Type": "application/json", ...headers },
    body: JSON.stringify(body),
  });
  const data = await res.json();
  return data as T;
}

async function getJson<T>(path: string, headers: Record<string, string> = {}): Promise<T> {
  const res = await fetch(apiUrl(path), { headers });
  if (!res.ok) throw new Error(`${res.status}: ${res.statusText}`);
  return (await res.json()) as T;
}

// --- Assist ---

export function assist(message: string, userId: string, opts?: { order_id?: string; return_reason?: string; session_id?: string }): Promise<ToolResponse> {
  const body: AssistRequest = { message };
  if (opts?.order_id) body.order_id = opts.order_id;
  if (opts?.return_reason) body.return_reason = opts.return_reason;
  if (opts?.session_id) body.session_id = opts.session_id;
  return postJson("/assist", body, { "X-User-Id": userId });
}

// --- Tools ---

export function queryOrderLogistics(orderId: string, userId: string): Promise<ToolResponse> {
  return postJson("/tools/query-order-logistics", { order_id: orderId }, { "X-User-Id": userId });
}

export function submitReturnApplication(orderId: string, returnReason: string, idempotencyKey: string, userId: string): Promise<ToolResponse> {
  return postJson("/tools/submit-return-application", { order_id: orderId, return_reason: returnReason, idempotency_key: idempotencyKey }, { "X-User-Id": userId });
}

export function getReturnApplication(applicationId: string, userId: string): Promise<ToolResponse> {
  return getJson(`/tools/return-applications/${applicationId}`, { "X-User-Id": userId });
}

export function getTicket(ticketId: string, userId: string): Promise<ToolResponse> {
  return getJson(`/tools/tickets/${ticketId}`, { "X-User-Id": userId });
}

// --- Agent ---

export interface TicketListResponse {
  tickets: Ticket[];
  pagination: { page: number; page_size: number; total: number };
}

export interface ApplicationListResponse {
  applications: ReturnApplication[];
  pagination: { page: number; page_size: number; total: number };
}

export function listTickets(params: { page?: number; page_size?: number; keyword?: string; status?: string; category?: string }, role: string, userId: string): Promise<TicketListResponse> {
  const search = new URLSearchParams();
  if (params.page) search.set("page", String(params.page));
  if (params.page_size) search.set("page_size", String(params.page_size));
  if (params.keyword) search.set("keyword", params.keyword);
  if (params.status) search.set("status", params.status);
  if (params.category) search.set("category", params.category);
  return getJson(`/agent/tickets?${search}`, { "X-Role": role, "X-User-Id": userId });
}

export function listReturnApplications(params: { page?: number; page_size?: number; keyword?: string; status?: string }, role: string, userId: string): Promise<ApplicationListResponse> {
  const search = new URLSearchParams();
  if (params.page) search.set("page", String(params.page));
  if (params.page_size) search.set("page_size", String(params.page_size));
  if (params.keyword) search.set("keyword", params.keyword);
  if (params.status) search.set("status", params.status);
  return getJson(`/agent/return-applications?${search}`, { "X-Role": role, "X-User-Id": userId });
}

export function resolveTicket(ticketId: string, request: ResolveTicketRequest, role: string, userId: string): Promise<ToolResponse> {
  return postJson(`/agent/tickets/${ticketId}/resolve`, request, { "X-Role": role, "X-User-Id": userId });
}

export function reviewReturnApplication(applicationId: string, request: ReviewReturnRequest, role: string, userId: string): Promise<ToolResponse> {
  return postJson(`/agent/return-applications/${applicationId}/review`, request, { "X-Role": role, "X-User-Id": userId });
}

// --- Admin ---

export function getMetrics(): Promise<Metrics> {
  return getJson("/admin/metrics", { "X-Role": "supervisor" });
}

export function getTrace(traceId: string): Promise<TraceData> {
  return getJson(`/admin/traces/${traceId}`, { "X-Role": "supervisor" });
}

export function getObservabilitySummary(windowMinutes = 60): Promise<ObservabilitySummary> {
  return getJson(`/admin/observability/summary?window_minutes=${windowMinutes}`, { "X-Role": "supervisor" });
}

// --- Memory Inspector ---

export function listMemory(userId: string, memoryType?: string): Promise<MemoryListResponse> {
  const search = new URLSearchParams();
  if (memoryType) search.set("memory_type", memoryType);
  return getJson(`/admin/memory/${userId}?${search}`, { "X-Role": "supervisor" });
}
