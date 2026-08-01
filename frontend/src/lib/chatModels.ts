/** Shared chat model helpers (Auto Router detection, default preference resolve). */

export type ChatModelRef = {
  id: string;
  name?: string;
  external_id?: string;
};

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
