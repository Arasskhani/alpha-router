import { api, authFetch } from "../api";
/** No specialist Agent is bound to the chat, so turns use the plain model path. */
export const NO_AGENT_SELECTION = "none";
export const AUTO_AGENT_SELECTION = "auto";
/** Agents are mutually exclusive; re-picking the active one clears the binding. */
export function nextAgentSelection(current, slug) {
    if (!slug || slug === NO_AGENT_SELECTION)
        return NO_AGENT_SELECTION;
    return current === slug ? NO_AGENT_SELECTION : slug;
}
/**
 * Which Agent a chat runs with. An explicit ``null`` means the user switched the
 * Agent off, which must win over the Agent the server bound to earlier turns.
 */
export function resolveAgentSelection(chosenSlug, boundSlug) {
    if (chosenSlug === null)
        return NO_AGENT_SELECTION;
    return chosenSlug || boundSlug || NO_AGENT_SELECTION;
}
function optionalString(value) {
    return typeof value === "string" && value.trim() ? value.trim() : undefined;
}
export function agentCompletionMetadataFromSse(value) {
    if (!value || typeof value !== "object")
        return {};
    const raw = value;
    const citations = Array.isArray(raw.citations)
        ? raw.citations.filter((item) => Boolean(item
            && typeof item === "object"
            && optionalString(item.citation_id)))
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
export function agentRequestFields(selection) {
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
export async function fetchAgentCatalog() {
    return api("/api/agents", { cache: "no-store" });
}
export async function fetchPendingAgentHandoffs(sessionId) {
    const result = await api(`/api/agents/handoffs/pending?session_id=${encodeURIComponent(sessionId)}`, { cache: "no-store" });
    return Array.isArray(result.items) ? result.items : [];
}
export async function decideAgentHandoff(eventId, decision) {
    return api(`/api/agents/handoffs/${encodeURIComponent(eventId)}/${decision}`, { method: "POST" });
}
export async function fetchAgentCitation(runId, citationId) {
    return api(`/api/agents/citations/${encodeURIComponent(runId)}/${encodeURIComponent(citationId)}`, { cache: "no-store" });
}
/** Matches backend knowledge_citation_service markers embedded in agent answers. */
export const AGENT_CITATION_MARKER_RE = /\[\[cite:([A-Za-z0-9._:-]{1,128})\]\]/g;
/**
 * Stable [1]/[2] numbering for Verified sources and inline markers.
 * Prefer the citation list order so chips match the panel below the answer.
 */
export function buildCitationNumbering(citations, content = "") {
    const map = new Map();
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
export function formatAgentAnswerForDisplay(content, citations) {
    if (!content || !content.includes("[[cite:"))
        return content;
    const numbering = buildCitationNumbering(citations, content);
    return content.replace(AGENT_CITATION_MARKER_RE, (_full, id) => {
        const n = numbering.get(id);
        const label = n != null ? String(n) : "?";
        // U+2068 FIRST STRONG ISOLATE … U+2069 POP DIRECTIONAL ISOLATE
        return `\u2068[${label}]\u2069`;
    });
}
export function citationDisplayMarker(citation, index) {
    return `[${index + 1}]`;
}
function safeCitationFileName(value) {
    const cleaned = (value || "citation-source")
        .replace(/[<>:"/\\|?*\u0000-\u001f]/g, "_")
        .trim();
    return cleaned || "citation-source";
}
export async function openAgentCitationSource(runId, citation, mode) {
    const response = await authFetch(`/api/agents/citations/${encodeURIComponent(runId)}/${encodeURIComponent(citation.citation_id)}/content`, { cache: "no-store" });
    if (!response.ok) {
        let message = "Citation source is unavailable.";
        try {
            const body = (await response.json());
            if (body.detail)
                message = body.detail;
        }
        catch {
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
    }
    else {
        link.download = safeCitationFileName(citation.file_name);
    }
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(blobUrl), 60_000);
}
