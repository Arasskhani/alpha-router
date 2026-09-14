import { api, authFetch } from "../api";

/** No specialist Agent is bound to the chat, so turns use the plain model path. */
export const NO_AGENT_SELECTION = "none";
export const AUTO_AGENT_SELECTION = "auto";

/** Agents are mutually exclusive; re-picking the active one clears the binding. */
export function nextAgentSelection(current: string, slug: string): string {
  if (!slug || slug === NO_AGENT_SELECTION) return NO_AGENT_SELECTION;
  return current === slug ? NO_AGENT_SELECTION : slug;
}

/**
 * Which Agent a chat runs with. An explicit ``null`` means the user switched the
 * Agent off, which must win over the Agent the server bound to earlier turns.
 */
export function resolveAgentSelection(
  chosenSlug: string | null | undefined,
  boundSlug?: string | null,
): string {
  if (chosenSlug === null) return NO_AGENT_SELECTION;
  return chosenSlug || boundSlug || NO_AGENT_SELECTION;
}

export type AgentCatalogItem = {
  id: string;
  slug: string;
  name: string;
  description?: string | null;
  icon?: string | null;
  category?: string | null;
  version_id: string;
  version_number: number;
  citations_required: boolean;
  routing?: {
    enabled?: boolean;
    explicit_only?: boolean;
    description?: string | null;
    examples?: string[];
  };
  disclaimer?: Record<string, unknown>;
  locale?: Record<string, unknown>;
};

export type AgentCatalog = {
  items: AgentCatalogItem[];
  auto_route_available: boolean;
};

export type AgentCitation = {
  citation_id: string;
  marker?: string | null;
  title: string;
  file_name?: string | null;
  mime_type?: string | null;
  page_number?: number | null;
  section?: string | null;
  authority?: string | null;
  classification?: string | null;
  effective_from?: string | null;
  effective_to?: string | null;
  document_id?: string | null;
  document_version_id?: string | null;
  knowledge_base_id?: string | null;
  knowledge_base_name?: string | null;
  download_url?: string | null;
};

export type AgentHandoff = {
  id: string;
  turn_id: string;
  from_agent_id?: string | null;
  from_agent_name?: string | null;
  to_agent_id: string;
  to_agent_name?: string | null;
  reason: string;
  consent_required: boolean;
  created_at: string;
};

export type AgentHandoffDecision = {
  id: string;
  status: "accepted" | "completed" | "declined";
  agent_id?: string;
  agent_slug?: string;
  agent_name?: string;
};

export type AgentCompletionMetadata = {
  agentRunId?: string;
  agentId?: string;
  agentVersionId?: string;
  agentName?: string;
  agentStatus?: string;
  routingOutcome?: string;
  completionReasonCode?: string;
  citations?: AgentCitation[];
};

function optionalString(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() ? value.trim() : undefined;
}

export function agentCompletionMetadataFromSse(
  value: unknown,
): AgentCompletionMetadata {
  if (!value || typeof value !== "object") return {};
  const raw = value as Record<string, unknown>;
  const citations = Array.isArray(raw.citations)
    ? raw.citations.filter(
        (item): item is AgentCitation =>
          Boolean(
            item
            && typeof item === "object"
            && optionalString((item as Record<string, unknown>).citation_id),
          ),
      )
    : undefined;
  return {
    agentRunId: optionalString(raw.agent_run_id),
    agentId: optionalString(raw.agent_id),
    agentVersionId: optionalString(raw.agent_version_id),
    agentName: optionalString(raw.agent_name),
    agentStatus: optionalString(raw.agent_status),
    routingOutcome: optionalString(raw.routing_outcome),
    completionReasonCode: optionalString(raw.completion_reason_code),
    ...(citations ? { citations } : {}),
  };
}

export function agentRequestFields(selection: string): Record<string, unknown> {
  if (selection === AUTO_AGENT_SELECTION) {
    return { agent_auto_route: true, include_citations: true };
  }
  if (selection && selection !== NO_AGENT_SELECTION) {
    return {
      agent_slug: selection,
      agent_auto_route: false,
      include_citations: true,
    };
  }
  return { agent_auto_route: false };
}

export async function fetchAgentCatalog(): Promise<AgentCatalog> {
  return api<AgentCatalog>("/api/agents", { cache: "no-store" });
}

export async function fetchPendingAgentHandoffs(
  sessionId: string,
): Promise<AgentHandoff[]> {
  const result = await api<{ items: AgentHandoff[] }>(
    `/api/agents/handoffs/pending?session_id=${encodeURIComponent(sessionId)}`,
    { cache: "no-store" },
  );
  return Array.isArray(result.items) ? result.items : [];
}

export async function decideAgentHandoff(
  eventId: string,
  decision: "accept" | "decline",
): Promise<AgentHandoffDecision> {
  return api<AgentHandoffDecision>(
    `/api/agents/handoffs/${encodeURIComponent(eventId)}/${decision}`,
    { method: "POST" },
  );
}

export async function fetchAgentCitation(
  runId: string,
  citationId: string,
): Promise<AgentCitation> {
  return api<AgentCitation>(
    `/api/agents/citations/${encodeURIComponent(runId)}/${encodeURIComponent(citationId)}`,
    { cache: "no-store" },
  );
}

/** Matches backend knowledge_citation_service markers embedded in agent answers. */
export const AGENT_CITATION_MARKER_RE = /\[\[cite:([A-Za-z0-9._:-]{1,128})\]\]/g;

/**
 * Stable [1]/[2] numbering for Verified sources and inline markers.
 * Prefer the citation list order so chips match the panel below the answer.
 */
export function buildCitationNumbering(
  citations: AgentCitation[] | undefined | null,
  content = "",
): Map<string, number> {
  const map = new Map<string, number>();
  let next = 1;
  for (const citation of citations || []) {
    const id = citation?.citation_id;
    if (id && !map.has(id)) {
      map.set(id, next);
      next += 1;
    }
  }
  for (const match of content.matchAll(AGENT_CITATION_MARKER_RE)) {
    const id = match[1];
    if (id && !map.has(id)) {
      map.set(id, next);
      next += 1;
    }
  }
  return map;
}

/**
 * Replace long LTR ``[[cite:uuid]]`` tokens with short isolated ``[n]`` markers so
 * Persian/Arabic RTL paragraphs keep correct punctuation and wrapping.
 */
export function formatAgentAnswerForDisplay(
  content: string,
  citations?: AgentCitation[] | null,
): string {
  if (!content || !content.includes("[[cite:")) return content;
  const numbering = buildCitationNumbering(citations, content);
  return content.replace(AGENT_CITATION_MARKER_RE, (_full, id: string) => {
    const n = numbering.get(id);
    const label = n != null ? String(n) : "?";
    // U+2068 FIRST STRONG ISOLATE … U+2069 POP DIRECTIONAL ISOLATE
    return `\u2068[${label}]\u2069`;
  });
}

export function citationDisplayMarker(
  citation: AgentCitation,
  index: number,
): string {
  return `[${index + 1}]`;
}

function safeCitationFileName(value: string | null | undefined): string {
  const cleaned = (value || "citation-source")
    // eslint-disable-next-line no-control-regex -- control characters are exactly what is being stripped
    .replace(/[<>:"/\\|?*\u0000-\u001f]/g, "_")
    .trim();
  return cleaned || "citation-source";
}

export async function openAgentCitationSource(
  runId: string,
  citation: Pick<AgentCitation, "citation_id" | "file_name">,
  mode: "view" | "download",
): Promise<void> {
  const response = await authFetch(
    `/api/agents/citations/${encodeURIComponent(runId)}/${encodeURIComponent(citation.citation_id)}/content`,
    { cache: "no-store" },
  );
  if (!response.ok) {
    let message = "Citation source is unavailable.";
    try {
      const body = (await response.json()) as { detail?: string };
      if (body.detail) message = body.detail;
    } catch {
      // Keep the safe generic error for non-JSON responses.
    }
    throw new Error(message);
  }
  const blobUrl = URL.createObjectURL(await response.blob());
  const link = document.createElement("a");
  link.href = blobUrl;
  link.rel = "noopener noreferrer";
  if (mode === "view") {
    link.target = "_blank";
  } else {
    link.download = safeCitationFileName(citation.file_name);
  }
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(blobUrl), 60_000);
}
