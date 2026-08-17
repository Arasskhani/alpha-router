export type AgentPolicyMap = Record<string, Record<string, unknown>>;

export type AgentVersionRecord = {
  id: string;
  agent_id: string;
  version_number: number;
  status: "draft" | "review" | "published" | "archived";
  system_prompt?: string;
  policies: AgentPolicyMap;
  change_summary?: string | null;
  created_by_user_id?: number | null;
  submitted_at?: string | null;
  published_at?: string | null;
  created_at: string;
};

export type AgentBindingRecord = {
  id: string;
  agent_version_id: string;
  knowledge_base_id: string;
  knowledge_base_name?: string | null;
  knowledge_base_sensitivity?: string | null;
  release_mode: "latest" | "pinned";
  pinned_release_id?: string | null;
  status: string;
  retrieval_policy: Record<string, unknown>;
};

export type AgentRecord = {
  id: string;
  slug: string;
  name: string;
  description?: string | null;
  icon?: string | null;
  category?: string | null;
  status: "draft" | "active" | "archived";
  access_type: "public" | "private";
  acl_version: number;
  sort_order: number;
  is_system: boolean;
  active_version_id?: string | null;
  active_version_number?: number | null;
  versions: AgentVersionRecord[];
  bindings?: AgentBindingRecord[];
  created_at: string;
  updated_at: string;
};

export type AccessGrantInput = {
  target_type: "user" | "group" | "department" | "role";
  target: number | string;
  effect: "allow" | "deny";
};

export type ResourceAccessRecord = {
  access_type: "public" | "private";
  acl_version: number;
  grants: Array<
    AccessGrantInput & {
      id?: number | string;
      assigned_by_user_id?: number | null;
      assigned_at?: string | null;
    }
  >;
};

export type KnowledgeVersionRecord = {
  id: string;
  document_id: string;
  version_number: number;
  status: string;
  file_name: string;
  failure_reason?: string | null;
  mime_type: string;
  size_bytes: number;
  language?: string | null;
  classification: string;
  created_at: string;
};

export type KnowledgeBaseRecord = {
  id: string;
  slug: string;
  name: string;
  description?: string | null;
  status: string;
  access_type: "public" | "private";
  sensitivity: string;
  retention_days?: number | null;
  document_count: number;
  release_count: number;
  failed_job_count: number;
  documents?: Array<{
    id: string;
    canonical_key: string;
    title: string;
    status: string;
    created_at: string;
    updated_at: string;
    versions: KnowledgeVersionRecord[];
  }>;
  connectors?: Array<{
    id: string;
    name: string;
    connector_type: string;
    status: string;
    config?: { urls?: string[] } & Record<string, unknown>;
    sync_interval_minutes?: number | null;
    last_synced_at?: string | null;
  }>;
  releases?: Array<{
    id: string;
    version_number: number;
    status: string;
    change_summary?: string | null;
    created_at: string;
    published_at?: string | null;
  }>;
  indexes?: Array<{
    id: string;
    release_id: string;
    version_number: number;
    status: string;
    embedding_provider?: string | null;
    embedding_model?: string | null;
    expected_point_count?: number | null;
    indexed_point_count?: number | null;
    collection_alias?: string | null;
    failure_reason?: string | null;
    created_at?: string | null;
    activated_at?: string | null;
  }>;
  jobs?: Array<{
    id: string;
    job_type: string;
    status: string;
    attempt_count: number;
    max_attempts: number;
    error_message?: string | null;
    index_version_id?: string | null;
    document_version_id?: string | null;
    created_at: string;
  }>;
};

export type KnowledgeEmbeddingModel = {
  id: number;
  external_id: string;
  display_name?: string | null;
  provider: string;
  suggested_dimensions: number;
  embedding_fingerprint: string;
};

export type ToolVersionRecord = {
  id: string;
  tool_id: string;
  version_number: number;
  status: "draft" | "review" | "published" | "archived";
  handler_key: string;
  effect_type: "read_only" | "side_effecting";
  approval_mode: "never" | "required";
  timeout_seconds: number;
  max_retries: number;
  idempotent: boolean;
  input_schema: Record<string, unknown>;
  output_schema: Record<string, unknown>;
  change_summary?: string | null;
};

export type ToolRecord = {
  id: string;
  slug: string;
  name: string;
  description?: string | null;
  status: string;
  active_version_id?: string | null;
  active_version_number?: number | null;
  versions: ToolVersionRecord[];
};

export function agentStatusTone(status: string): string {
  const value = (status || "").toLowerCase();
  if (["active", "published", "succeeded", "approved", "ready"].includes(value)) {
    return "is-success";
  }
  if (
    [
      "review",
      "pending",
      "pending_kb_approval",
      "pending_domain_approval",
      "processing",
      "running",
      "leased",
      "building",
      "indexing",
      "draft",
    ].includes(value)
  ) {
    return "is-warning";
  }
  if (["failed", "dead", "blocked", "revoked", "suspended"].includes(value)) {
    return "is-danger";
  }
  if (["archived", "paused", "deleted"].includes(value)) {
    return "is-neutral";
  }
  return "is-neutral";
}

export function humanAgentStatus(status: string): string {
  return (status || "unknown")
    .replaceAll("_", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export function safeJsonObject(text: string, label: string): Record<string, unknown> {
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    throw new Error(`${label} must be valid JSON.`);
  }
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error(`${label} must be a JSON object.`);
  }
  return parsed as Record<string, unknown>;
}

export function readableDate(value?: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? value : date.toLocaleString();
}
