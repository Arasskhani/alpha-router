import { NO_AGENT_SELECTION } from "./agentChat";
import {
  copyFreshChatTools,
  normalizeChatTools,
  type ChatToolsState,
} from "./chatTools";
import type { ChatSession } from "./chatStorage";

export type ProjectChatComposerPrefs = {
  tools: ChatToolsState;
  toolsTouched: boolean;
  model: string;
  selectedAgentSlug: string | null;
};

export function emptyProjectChatComposerPrefs(): ProjectChatComposerPrefs {
  return {
    tools: copyFreshChatTools(),
    toolsTouched: false,
    model: "",
    selectedAgentSlug: null,
  };
}

export function normalizeProjectChatComposerPrefs(
  raw?: Partial<ProjectChatComposerPrefs> | null,
): ProjectChatComposerPrefs {
  const empty = emptyProjectChatComposerPrefs();
  if (!raw) return empty;
  const slug = typeof raw.selectedAgentSlug === "string" ? raw.selectedAgentSlug.trim() : "";
  return {
    tools: raw.toolsTouched ? normalizeChatTools(raw.tools) : copyFreshChatTools(),
    toolsTouched: !!raw.toolsTouched,
    model: typeof raw.model === "string" ? raw.model.trim() : "",
    selectedAgentSlug:
      !slug || slug === NO_AGENT_SELECTION ? null : slug,
  };
}

export type ProjectChatSessionComposer = ChatSession & {
  tools: ChatToolsState;
  toolsTouched: boolean;
};

/** Overlay this user's composer prefs onto a shared project ChatSession row. */
export function overlayComposerPrefsOnSession(
  session: ChatSession,
  prefs: ProjectChatComposerPrefs | null | undefined,
): ProjectChatSessionComposer {
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
