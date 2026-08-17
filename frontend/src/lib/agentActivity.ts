import { humanAgentStatus } from "./agentPlatform";

export const AGENT_ACTIVITY_PATH = "/admin/agent-activity";

export type RuntimeHealthStatus = "blocked" | "failed";

export type ActivityQuery = {
  source: string;
  status: string;
  sinceHours: string;
};

export function runtimeHealthHref(status?: RuntimeHealthStatus): string {
  const params = new URLSearchParams({ source: "runtime", since_hours: "24" });
  if (status) params.set("status", status);
  return `${AGENT_ACTIVITY_PATH}?${params.toString()}`;
}

export function parseActivityQuery(search: URLSearchParams): ActivityQuery {
  const status = (search.get("status") || "").trim();
  const source = (search.get("source") || "all").trim() || "all";
  return {
    source: status && source === "all" ? "runtime" : source,
    status,
    sinceHours: (search.get("since_hours") || "").trim(),
  };
}

export function activityApiPath(query: ActivityQuery, limit = 250): string {
  const params = new URLSearchParams({ limit: String(limit) });
  if (query.source && query.source !== "all") params.set("source", query.source);
  if (query.status) params.set("status", query.status);
  if (query.sinceHours) params.set("since_hours", query.sinceHours);
  return `/api/admin/agents/activity?${params.toString()}`;
}

export function nextActivitySearch(
  current: URLSearchParams,
  patch: Partial<ActivityQuery>,
): URLSearchParams {
  const next = new URLSearchParams(current);
  const parsed = { ...parseActivityQuery(current), ...patch };
  if (!parsed.source || parsed.source === "all") next.delete("source");
  else next.set("source", parsed.source);
  if (!parsed.status || parsed.source !== "runtime") next.delete("status");
  else next.set("status", parsed.status);
  if (!parsed.sinceHours) next.delete("since_hours");
  else next.set("since_hours", parsed.sinceHours);
  return next;
}

export function humanActivityEventType(eventType: string): string {
  if (eventType.startsWith("agent.run.")) {
    return `Run ${humanAgentStatus(eventType.slice("agent.run.".length)).toLowerCase()}`;
  }
  return humanAgentStatus(eventType);
}
