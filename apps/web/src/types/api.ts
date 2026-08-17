// API 类型定义 — 与后端 schemas.py 对齐

export type Role = "consumer" | "agent" | "supervisor" | "implementer";

export interface AssistRequest {
  message: string;
  order_id?: string;
  return_reason?: string;
  session_id?: string;
}

export interface ToolResponse<T = Record<string, unknown>> {
  success: boolean;
  data: T | null;
  error_code: string | null;
  message: string;
  trace_id: string;
  http_status?: number;
  handoff?: boolean;
}

export interface Citation {
  policy_id: string;
  title: string;
  version: string;
  status: string;
  effective_from: string;
  effective_to: string | null;
  source: string;
  chunk_id: string;
  quoted_text: string;
}

export interface OrderLogisticsData {
  order_id: string;
  order_status: string;
  carrier: string;
  latest_event: {
    occurred_at: string;
    location: string;
    description: string;
  };
  exception: boolean;
  estimated_arrival: string | null;
}

export interface ReturnEligibilityData {
  order_id: string;
  eligible: boolean;
  decision: string;
  rule_version: string;
  basis: string;
  next_steps: string[];
  requires_human: boolean;
}

export interface ReturnApplication {
  application_id: string;
  order_id: string;
  reason: string;
  status: string;
  next_steps: string[];
  notice: string;
  submitted_at: string;
  reviewed_at: string | null;
  reviewer: string | null;
  review_reason: string | null;
}

export interface Ticket {
  ticket_id: string;
  order_id: string | null;
  category: string;
  priority: string;
  status: string;
  created_at: string;
  summary?: Record<string, unknown> | string;
  handoff_reason?: string;
  agent_reply?: string | null;
}

export interface TicketSummary {
  user_request?: string;
  order_id?: string | null;
  actions_taken?: string[];
  handoff_reason?: string;
  secondary_intents?: string[];
  risk_labels?: string[];
  intent_catalog_version?: string;
}

export interface Metrics {
  event_count: number;
  tool_calls: number;
  tool_error_rate: number;
  tool_success_rate: number | null;
  handoff_count: number;
  handoff_rate: number | null;
  conversation_count: number;
  citation_rate: number | null;
  risk_count: number;
  status: string;
  intent_distribution: Record<string, number>;
  error_distribution: Record<string, number>;
  trend: TrendBucket[];
}

export interface TrendBucket {
  label: string;
  conversations: number;
  handoffs: number;
  tool_success_rate: number | null;
}

export interface TraceSpan {
  span_id: string;
  trace_id: string;
  parent_span_id: string | null;
  name: string;
  kind: string;
  started_at: string;
  ended_at: string;
  duration_ms: number;
  status: string;
  error_code: string | null;
  error_type: string | null;
  attributes: Record<string, unknown>;
}

export interface TraceData {
  trace: {
    trace_id: string;
    name: string;
    route: string;
    method: string;
    started_at: string;
    ended_at: string | null;
    duration_ms: number | null;
    status: string;
    status_code: number | null;
    error_code: string | null;
    error_type: string | null;
    attributes: Record<string, unknown>;
  };
  spans: TraceSpan[];
}

export interface ObservabilitySummary {
  window_minutes: number;
  request_count: number;
  request_error_count: number;
  request_error_rate: number;
  request_latency_ms: {
    avg: number | null;
    p50: number | null;
    p95: number | null;
    max: number | null;
  };
  errors_by_code: Record<string, number>;
  operations: Array<{
    operation: string;
    count: number;
    error_count: number;
    error_rate: number;
    latency_ms: { avg: number; p50: number | null; p95: number | null; max: number };
  }>;
  slowest_traces: Array<{ trace_id: string; route: string; duration_ms: number; status: string }>;
  recent_failed_traces: Array<{ trace_id: string; route: string; duration_ms: number; error_code: string; error_type: string }>;
  recent_failed_spans: Array<{ trace_id: string; span_id: string; operation: string; duration_ms: number; error_code: string; error_type: string }>;
}

// Memory Inspector 类型
export interface MemoryItem {
  memory_id: string;
  user_id: string;
  memory_type: string;
  key: string;
  value: unknown;
  source: string;
  confidence: number;
  scope: string;
  scope_order_id: string | null;
  session_id: string | null;
  created_at: string;
  updated_at: string;
  expires_at: string | null;
  status: string;
}

export interface MemoryListResponse {
  user_id: string;
  memories: MemoryItem[];
  total: number;
}

// Agent 工单/退货申请操作类型
export interface ResolveTicketRequest {
  agent_reply: string;
  review_reason: string;
}

export interface ReviewReturnRequest {
  decision: "approve" | "reject";
  review_reason: string;
}
