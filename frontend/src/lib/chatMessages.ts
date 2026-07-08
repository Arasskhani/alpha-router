/** Shown in Chat when no models are enabled / available. */
export const CHAT_NO_MODELS_MESSAGE =
  "No models are currently available. Contact your administrator";

const LEGACY_NO_MODELS_PATTERNS = [
  "No enabled models",
  "Enable models in Admin",
] as const;

export function chatModelsEmptyMessage(): string {
  return CHAT_NO_MODELS_MESSAGE;
}

/** Map older API/UI copy to the current user-facing message. */
export function normalizeChatModelsError(err: unknown): string {
  const msg = String(err);
  if (LEGACY_NO_MODELS_PATTERNS.some((p) => msg.includes(p))) {
    return CHAT_NO_MODELS_MESSAGE;
  }
  return msg;
}
