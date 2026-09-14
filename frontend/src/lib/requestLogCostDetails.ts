import { api } from "../api";

export type RequestLogSummary = {
  id: number;
  request_time: string;
  username: string;
  identity_type?: "user" | "api_key" | "chat";
  api_key_name?: string;
  api_key_kind?: "gateway" | "personal";
  api_key_prefix?: string;
  user_api_key_id?: number;
  alpha_router_api_key_id?: number;
  app?: string;
  source?: string;
  client_app?: string;
  provider?: string;
  model_id: string;
  prompt_language: string;
  prompt_tokens: number;
  completion_tokens: number;
  cached_tokens?: number;
  total_cost_usd: number;
  provider_cost_usd?: number | null;
  calculated_cost_usd?: number | null;
  cost_source?: string;
  cost_confidence?: "exact" | "reconciled" | "calculated" | "estimated" | "unknown";
  has_unpriced_usage?: boolean;
  reconciled_at?: string | null;
  response_time_ms: number;
  source_ip: string;
  success: boolean;
};

type CostLineItem = {
  category: string;
  quantity: number;
  unit: string;
  unit_price_usd: number | null;
  cost_usd: number | null;
  pricing_source: string;
};

type CostEvent = {
  id: string;
  provider_type: string;
  service_type: string;
  operation_name: string;
  model_id: string | null;
  attempt_index: number;
  upstream_request_id: string | null;
  status: string;
  prompt_tokens: number;
  completion_tokens: number;
  cached_tokens: number;
  cache_write_tokens: number;
  reasoning_tokens: number;
  provider_cost_usd: number | null;
  calculated_cost_usd: number | null;
  final_cost_usd: number | null;
  cost_source: string;
  cost_confidence: string;
  reconciliation_attempts: number;
  last_reconciliation_attempt_at: string | null;
  error_message: string | null;
  line_items: CostLineItem[];
};

export type CostDetails = {
  operation: {
    id: string;
    operation_type: string;
    status: string;
    total_cost_usd: number;
    provider_cost_usd: number | null;
    calculated_cost_usd: number | null;
    unpriced_event_count: number;
    reconciled_at: string | null;
  } | null;
  events: CostEvent[];
  legacy: boolean;
  total_cost_usd?: number;
};

export function isPersonalApiKeyLog(log: Pick<RequestLogSummary, "api_key_kind" | "source" | "user_api_key_id">): boolean {
  if (log.api_key_kind === "personal") return true;
  if (typeof log.user_api_key_id === "number" && log.user_api_key_id > 0) return true;
  return (log.source || "").trim().toLowerCase() === "user_key";
}

export function logIdentityLabel(log: RequestLogSummary): string {
  if (log.identity_type === "api_key") {
    return `${log.api_key_name || log.username || "API key"} (Gateway API Key)`;
  }
  if (isPersonalApiKeyLog(log)) {
    const user = log.username || "unknown";
    const keyName = (log.api_key_name || "").trim();
    if (keyName && keyName.toLowerCase() !== user.toLowerCase()) {
      return `${user} · ${keyName} (Personal API Key)`;
    }
    return `${user} (Personal API Key)`;
  }
  if (log.identity_type === "chat") {
    return `${log.username || "unknown"} (Chat)`;
  }
  return log.username || "unknown";
}

export function confidenceLabel(key: string, unpriced = false) {
  if (unpriced) return { key: "unknown", label: "Unpriced" };
  const labels: Record<string, string> = {
    exact: "Provider",
    reconciled: "Reconciled",
    calculated: "Catalog",
    estimated: "Estimated",
    unknown: "Unknown",
  };
  return { key: key || "unknown", label: labels[key] || key || "Unknown" };
}

export function money(n: number | null | undefined) {
  return n == null || Number.isNaN(n) ? "—" : `$${n.toFixed(8)}`;
}

export function formatTokenCount(n: number) {
  return new Intl.NumberFormat("en-US").format(n || 0);
}

export async function fetchOwnedRequestLog(logId: number): Promise<RequestLogSummary> {
  return api<RequestLogSummary>(`/api/user/request-logs/${logId}`);
}

export async function fetchOwnedRequestLogCostDetails(logId: number): Promise<CostDetails> {
  return api<CostDetails>(`/api/user/request-logs/${logId}/cost-details`);
}

export async function fetchAdminRequestLogCostDetails(logId: number): Promise<CostDetails> {
  return api<CostDetails>(`/api/admin/logs/${logId}/cost-details`);
}
