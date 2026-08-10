/** Shared chat model helpers (Auto Router detection, default preference resolve). */

export type ChatModelRef = {
  id: string;
  name?: string;
  external_id?: string;
  /** Provider capability tags from the catalog (`text`, `rerank`, `embeddings`, …). */
  kinds?: string[];
};

/**
 * True when the model can answer text chat completions.
 * Missing `kinds` is treated as text-capable for backward compatibility with
 * older API payloads; pure rerank/embeddings models always advertise kinds.
 */
export function modelSupportsTextChat(m?: ChatModelRef | null): boolean {
  if (!m) return false;
  if (isAutoRouterModel(m)) return true;
  const kinds = m.kinds?.length ? m.kinds : ["text"];
  return kinds.includes("text");
}

export const AUTO_ROUTER_EXTERNAL_ID = "openrouter/auto";

/** True for openrouter/auto, openrouter/auto-beta, and display name "Auto Router*". */
export function isAutoRouterExternalId(externalId?: string | null): boolean {
  const low = (externalId || "").trim().toLowerCase();
  if (!low) return false;
  if (low === AUTO_ROUTER_EXTERNAL_ID || low === "auto" || low === "openrouter/auto-beta") {
    return true;
  }
  if (low.endsWith("/auto") || low.endsWith(":auto")) return true;
  const tail = low.includes("/") ? low.slice(low.lastIndexOf("/") + 1) : low;
  return tail === "auto" || tail.startsWith("auto-");
}

export function isAutoRouterModel(m?: ChatModelRef | null): boolean {
  if (!m) return false;
  if (isAutoRouterExternalId(m.external_id)) return true;
  const name = (m.name || "").trim().toLowerCase();
  return name === "auto router" || name.startsWith("auto router ");
}

export function findAutoRouterModel(models: ChatModelRef[]): ChatModelRef | undefined {
  return models.find(isAutoRouterModel);
}

/** Prefer Auto Router, otherwise the first text-capable catalog model. */
export function findTextChatFallbackModel<T extends ChatModelRef>(models: T[]): T | undefined {
  const autoRouter = models.find((m) => isAutoRouterModel(m) && modelSupportsTextChat(m));
  if (autoRouter) return autoRouter;
  return models.find((m) => modelSupportsTextChat(m));
}

/**
 * Pick a model for short helper calls (To ENG / prompt assist).
 * Prefer the user's current selection when it is text-capable; otherwise a
 * concrete text model, then Auto Router.
 */
export function resolvePromptAssistModel<T extends ChatModelRef>(
  models: T[],
  preferredId?: string | null,
): T | undefined {
  const preferred =
    models.find((m) => m.id === preferredId) ||
    models.find((m) => (m.external_id || "").trim() === (preferredId || "").trim());
  if (preferred && modelSupportsTextChat(preferred)) {
    return preferred;
  }
  const concrete = models.find((m) => modelSupportsTextChat(m) && !isAutoRouterModel(m));
  if (concrete) return concrete;
  return findTextChatFallbackModel(models);
}

/**
 * Resolve a saved default-model preference against the live catalog.
 * Returns "" when unset or when the saved id is no longer in the catalog.
 * No model id is hardcoded here — only the user's saved preference is honored.
 */
export function resolveDefaultModelPreference(
  models: ChatModelRef[],
  saved: string | null | undefined,
): string {
  const raw = (saved || "").trim();
  if (!raw) return "";
  if (models.some((m) => m.id === raw)) return raw;
  const byExternal = models.find((m) => (m.external_id || "").trim() === raw);
  if (byExternal) return byExternal.id;
  return "";
}
