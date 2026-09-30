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
  /** What kind of request this was: chat, video, image, speech, embedding… */
  operation_type?: string | null;
  error_message?: string | null;
  /** Classified failure (timeout, connect_error, http_client_error, …). */
  error_code?: string | null;
  http_status?: number | null;
  /** Ties the row to the container log lines for the same request or job. */
  correlation_id?: string | null;
  provider_job_id?: string | null;
};

type CostLineItem = {
  category: string;
  quantity: number;
  unit: string;
  unit_price_usd: number | null;
  cost_usd: number | null;
  pricing_source: string;
};

type RequestFailureBlock = {
  id: number;
  success: boolean;
  error_code: string | null;
  error_message: string | null;
  http_status: number | null;
  response_time_ms: number;
  source: string | null;
  client_app: string | null;
  model_id: string | null;
  // Operator-only: the admin endpoint sends these, the user-facing one omits
  // them entirely, so they are optional rather than nullable.
  correlation_id?: string | null;
  provider_job_id?: string | null;
  source_ip?: string | null;
  /** Operator-only: what a chat turn was given beside its messages (ids and counts). */
  memory_context?: MemoryContext | null;
  project_id: string | null;
};

/** What a chat turn was given beside its messages, as its request log keeps it (``memory_context``). */
export type MemoryContext = {
  memories?: number;
  project_memories?: number;
  recalled_chats?: string[];
  context_fit?: {
    dropped: number;
    summarized: number;
    window?: number | null;
    budget?: number | null;
    tokens_before?: number;
    tokens_after?: number;
    summary?: { up_to?: number | null; version?: string | null; tokens?: number } | null;
  } | null;
};

/** The Memory and context rows of a request's details: one label and value each; none when nothing was given. */
export function memoryContextRows(
  context: MemoryContext | null | undefined,
  formatTime: (iso: string) => string,
): { label: string; value: string }[] {
  if (!context) return [];
  const rows: { label: string; value: string }[] = [];
  const memories = [
    context.memories ? `${context.memories} personal` : "",
    context.project_memories ? `${context.project_memories} project` : "",
  ].filter(Boolean);
  if (memories.length) rows.push({ label: "Memories", value: memories.join(" · ") });
  const chats = context.recalled_chats ?? [];
  if (chats.length) {
    rows.push({ label: `Earlier chats read (${chats.length})`, value: chats.join(", ") });
  }
  const fit = context.context_fit;
  if (fit && fit.dropped) {
    const parts = [
      `${fit.dropped} older message${fit.dropped === 1 ? "" : "s"}` +
        (fit.summarized ? ` (${fit.summarized} read as the summary)` : ""),
    ];
    if (fit.window) parts.push(`window ${formatTokenCount(fit.window)} tokens`);
    if (fit.tokens_before && fit.tokens_after) {
      parts.push(`${formatTokenCount(fit.tokens_before)} → ${formatTokenCount(fit.tokens_after)} tokens`);
    }
    rows.push({ label: "Left out to fit", value: parts.join(" · ") });
    const summary = fit.summary;
    if (fit.summarized && summary) {
      const about = [
        summary.up_to ? `up to message #${summary.up_to}` : "",
        summary.tokens ? `about ${formatTokenCount(summary.tokens)} tokens` : "",
        summary.version ? `written ${formatTime(summary.version)}` : "",
      ].filter(Boolean);
      rows.push({ label: "Summary used", value: about.join(" · ") || "Yes" });
    }
  }
  return rows;
}

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
  /**
   * Operator-only, and absent from the user-facing endpoint: the provider's own
   * response for this attempt (kept until the retention window passes) and the
   * connection row the call went out on.
   */
  raw_usage?: Record<string, unknown> | null;
  connection_id?: number | null;
  quantity: number | null;
  unit: string | null;
  started_at: string | null;
  completed_at: string | null;
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
    accounting_status?: string | null;
    metadata?: Record<string, unknown> | null;
    started_at?: string | null;
    completed_at?: string | null;
    reconciled_at: string | null;
  } | null;
  events: CostEvent[];
  legacy: boolean;
  request?: RequestFailureBlock | null;
  /** Admin view only: how long the raw provider responses below are kept. */
  raw_payload_retention_days?: number | null;
  total_cost_usd?: number;
};

/** Short label for the kind of request, for the Type column and its filter. */
export function operationTypeLabel(value: string | null | undefined): string {
  const key = (value || "").trim().toLowerCase();
  const labels: Record<string, string> = {
    chat: "Chat",
    video: "Video",
    image: "Image",
    speech: "Speech",
    transcription: "Transcription",
    embedding: "Embedding",
    rerank: "Rerank",
    memory_extract: "Memory learning",
    chat_summary: "Chat summary",
    chat_recall_embed: "Chat recall index",
  };
  return labels[key] || (key ? key.charAt(0).toUpperCase() + key.slice(1) : "—");
}

/** Human wording for a classified failure; unknown codes pass through readably. */
export function errorCodeLabel(value: string | null | undefined): string {
  const key = (value || "").trim().toLowerCase();
  const labels: Record<string, string> = {
    timeout: "Timed out",
    connect_error: "Could not connect",
    network_error: "Network error",
    http_client_error: "Rejected by provider",
    http_server_error: "Provider error",
    invalid_response: "Unusable response",
    provider_error: "Provider error",
    empty_completion: "Empty completion",
    cancelled: "Cancelled",
    client_disconnected: "Client disconnected",
    reclaimed: "Reclaimed",
  };
  return labels[key] || key.replace(/_/g, " ");
}

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
