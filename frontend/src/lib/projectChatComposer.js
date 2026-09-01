import { NO_AGENT_SELECTION } from "./agentChat";
import { copyFreshChatTools, normalizeChatTools, } from "./chatTools";
export function emptyProjectChatComposerPrefs() {
    return {
        tools: copyFreshChatTools(),
        toolsTouched: false,
        model: "",
        selectedAgentSlug: null,
    };
}
export function normalizeProjectChatComposerPrefs(raw) {
    const empty = emptyProjectChatComposerPrefs();
    if (!raw)
        return empty;
    const slug = typeof raw.selectedAgentSlug === "string" ? raw.selectedAgentSlug.trim() : "";
    return {
        tools: raw.toolsTouched ? normalizeChatTools(raw.tools) : copyFreshChatTools(),
        toolsTouched: !!raw.toolsTouched,
        model: typeof raw.model === "string" ? raw.model.trim() : "",
        selectedAgentSlug: !slug || slug === NO_AGENT_SELECTION ? null : slug,
    };
}
/** Overlay this user's composer prefs onto a shared project ChatSession row. */
export function overlayComposerPrefsOnSession(session, prefs) {
    const normalized = normalizeProjectChatComposerPrefs(prefs);
    return {
        ...session,
        tools: normalized.tools,
        toolsTouched: normalized.toolsTouched,
        model: normalized.model || session.model,
        selectedAgentSlug: normalized.selectedAgentSlug,
        currentAgentId: normalized.selectedAgentSlug ? session.currentAgentId : null,
        currentAgentVersionId: normalized.selectedAgentSlug
            ? session.currentAgentVersionId
            : null,
    };
}
