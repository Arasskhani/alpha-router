/**
 * Guardrails (Admin › Guardrails): the shapes the admin API returns, and the
 * small rules the forms share. Every rule and pattern is the administrator's;
 * the page never creates one by itself.
 */

export const GUARDRAILS_BASE = "/api/admin/guardrails";

export type Channel = "chat" | "attachments" | "context" | "extension" | "gateway" | "web_search" | "web_fetch";
export type TrustLevel = "internal" | "trusted" | "public";
export type RuleAction = "block" | "redact" | "route";
export type RuleMode = "off" | "monitor" | "enforce";
type PatternKind = "regex" | "words" | "domains";

export type LibraryPattern = {
  ref: string;
  name: string;
  description: string;
  kind: PatternKind;
  expression: string;
  validator: string | null;
  redact_label: string;
  case_sensitive: boolean;
  normalize: boolean;
  must_match: string[];
  must_not_match: string[];
  used_by?: string[];
  hits_7d?: number;
};

export type GuardrailsMeta = {
  channels: { key: Channel; label: string }[];
  routable_channels: Channel[];
  redactable_channels: Channel[];
  trust_levels: { key: TrustLevel; label: string }[];
  validators: { key: string; label: string }[];
  default_messages: Record<RuleAction, string>;
  library: LibraryPattern[];
  route_models: { id: number; label: string; trust_level: TrustLevel }[];
};

export type PatternDraft = {
  name: string;
  description: string;
  kind: PatternKind;
  expression: string;
  entries: string[];
  case_sensitive: boolean;
  normalize: boolean;
  context_words: string[];
  context_window: number;
  validator: string | null;
  never_match: string[];
  redact_label: string;
  must_match: string[];
  must_not_match: string[];
};

export type CustomPattern = PatternDraft & {
  id: number;
  ref: string;
  version: number;
  used_by: string[];
  hits_7d: number;
};

export type PatternsResponse = { custom: CustomPattern[]; library: LibraryPattern[] };

export type RuleDraft = {
  name: string;
  description: string;
  mode: RuleMode;
  patterns: string[];
  match_mode: "any" | "all";
  min_matches: number;
  channels: Channel[];
  destinations: TrustLevel[];
  action: RuleAction;
  route_model_id: number | null;
  user_message: string;
};

export type Rule = RuleDraft & {
  id: number;
  position: number;
  pattern_names: string[];
  missing_patterns: string[];
  route_model_label: string | null;
  access_type: "public" | "private";
  allow_count: number;
  deny_count: number;
  version: number;
  hits_7d: number;
  updated_at: string | null;
};

export type GuardrailEvent = {
  id: number;
  created_at: string | null;
  rule_id: number | null;
  rule_name: string | null;
  rule_version: number | null;
  action: "block" | "redact" | "route" | "monitor" | "engine_error";
  intended_action: RuleAction | null;
  channel: string;
  destination: string | null;
  destination_trust: TrustLevel | null;
  username: string | null;
  alpha_router_api_key_id: number | null;
  source: string | null;
  model_ref: string | null;
  match_count: number;
  findings: { ref: string; name: string; count: number; hints: string[] }[];
  message: string | null;
};

export type Overview = {
  rules: Record<RuleMode, number>;
  totals_7d: Record<"block" | "redact" | "route" | "monitor" | "engine_error", number>;
  top_by_action: Partial<Record<string, { name: string; count: number }[]>>;
  by_channel: { channel: string; count: number }[];
  top_rules: { rule_id: number; name: string; count: number }[];
  daily: { date: string; block: number; redact: number; route: number; monitor: number }[];
};

export type GuardrailSettings = {
  fail_closed: boolean;
  restore_replies: boolean;
  event_retention_days: number;
  alert_emails: string[];
};

export const ACTION_LABELS: Record<string, string> = {
  block: "Block",
  redact: "Redact",
  route: "Route",
  monitor: "Monitored",
  engine_error: "Engine error",
};

export const MODE_LABELS: Record<RuleMode, string> = { off: "Off", monitor: "Monitor", enforce: "Enforce" };

export const EMPTY_PATTERN: PatternDraft = {
  name: "",
  description: "",
  kind: "regex",
  expression: "",
  entries: [],
  case_sensitive: false,
  normalize: true,
  context_words: [],
  context_window: 50,
  validator: null,
  never_match: [],
  redact_label: "REDACTED",
  must_match: [],
  must_not_match: [],
};

export const EMPTY_RULE: RuleDraft = {
  name: "",
  description: "",
  mode: "monitor",
  patterns: [],
  match_mode: "any",
  min_matches: 1,
  channels: ["chat", "attachments"],
  destinations: [],
  action: "redact",
  route_model_id: null,
  user_message: "",
};

/** One value per line in a textarea; blank lines dropped. */
export function lines(text: string): string[] {
  return text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
}

/** Comma- or line-separated words (context words). */
export function words(text: string): string[] {
  return text
    .split(/[,،\n]/)
    .map((w) => w.trim())
    .filter(Boolean);
}

/** What is wrong with a rule before it is sent, said plainly; "" when nothing is. */
export function ruleProblem(rule: RuleDraft, meta: GuardrailsMeta | null): string {
  if (!rule.name.trim()) return "Name the rule.";
  if (!rule.patterns.length) return "Choose at least one pattern to detect.";
  if (!rule.channels.length) return "Choose at least one channel.";
  if (!Number.isInteger(rule.min_matches) || rule.min_matches < 1) return "At least 1 match.";
  if (rule.action === "route") {
    if (!rule.route_model_id) return "Choose the model to route to.";
    const routable = new Set(meta?.routable_channels ?? []);
    if (rule.channels.some((c) => !routable.has(c))) {
      return "Only chat, attached files, the extension and the Gateway can be routed to another model.";
    }
  }
  if (rule.action === "redact") {
    const redactable = new Set(meta?.redactable_channels ?? []);
    if (rule.channels.some((c) => !redactable.has(c))) return "An address read by Web Fetch cannot be masked: block it.";
  }
  return "";
}

/** Rules as the table says what they look at: "Chat, Attachments → Public". */
export function channelsSummary(rule: Rule, meta: GuardrailsMeta | null): { channels: string[]; destinations: string[] } {
  const channelLabel = (c: string) =>
    ({ chat: "Chat", attachments: "Attachments", context: "Context", extension: "Extension", gateway: "Gateway", web_search: "Web search", web_fetch: "Web fetch" })[c] ?? c;
  const trustLabel = (t: string) => meta?.trust_levels.find((x) => x.key === t)?.label ?? t;
  return {
    channels: rule.channels.length === (meta?.channels.length ?? 7) ? ["All channels"] : rule.channels.map(channelLabel),
    destinations: rule.destinations.length ? rule.destinations.map(trustLabel) : ["Everywhere"],
  };
}

export function formatWhen(value: string | null): string {
  if (!value) return "";
  const date = new Date(value.endsWith("Z") ? value : `${value}Z`);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}
