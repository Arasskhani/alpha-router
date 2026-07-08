/** Shared chat model helpers (system default, Auto Router, etc.). */

export type ChatModelRef = {
  id: string;
  name?: string;
  external_id?: string;
};

export const AUTO_ROUTER_EXTERNAL_ID = "openrouter/auto";
export const GROK_43_EXTERNAL_ID = "x-ai/grok-4.3";

export function isAutoRouterModel(m?: ChatModelRef | null): boolean {
  if (!m) return false;
  const ext = (m.external_id || "").trim().toLowerCase();
  if (ext === AUTO_ROUTER_EXTERNAL_ID) return true;
  return (m.name || "").trim().toLowerCase() === "auto router";
}

export function findAutoRouterModel(models: ChatModelRef[]): ChatModelRef | undefined {
  return models.find(isAutoRouterModel);
}

export function isGrok43Model(m?: ChatModelRef | null): boolean {
  if (!m) return false;
  const ext = (m.external_id || "").trim().toLowerCase();
  if (ext === GROK_43_EXTERNAL_ID) return true;
  return (m.name || "").trim().toLowerCase() === "grok 4.3";
}

export function findGrok43Model(models: ChatModelRef[]): ChatModelRef | undefined {
  return models.find(isGrok43Model);
}

/** System default for new chats when the user has no personal default saved. */
export function resolveSystemDefaultModel(models: ChatModelRef[]): ChatModelRef | undefined {
  return findGrok43Model(models);
}

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

/** One-time migration: empty default or explicit Auto Router → Grok 4.3. */
export function shouldMigrateDefaultToGrok43(
  models: ChatModelRef[],
  defaultModelId: string | null | undefined,
): boolean {
  if (!findGrok43Model(models)) return false;
  const id = (defaultModelId || "").trim();
  if (!id) return true;
  const saved = models.find((m) => m.id === id);
  if (!saved) return false;
  return isAutoRouterModel(saved);
}
