/** Code Interpreter model compatibility, driven only by backend evidence. */

import { isAutoRouterModel, type ChatModelRef } from "./chatModels";

type CodeInterpreterCompatibilityStatus =
  | "compatible"
  | "unknown"
  | "probing"
  | "degraded"
  | "incompatible";

export type CodeInterpreterCompatibility = {
  status: CodeInterpreterCompatibilityStatus;
  compatible: boolean;
  /** Backend decides selectability; unknown models stay usable for new releases. */
  selectable: boolean;
  auto_router?: boolean;
  verified?: boolean;
  score?: number | null;
  reason_code?: string | null;
  reason_detail?: string | null;
  manual_override?: string | null;
  last_probe_at?: string | null;
  last_success_at?: string | null;
  last_failure_at?: string | null;
  next_probe_at?: string | null;
  quarantine_until?: string | null;
};

export type CodeInterpreterModelRef = ChatModelRef & {
  code_interpreter?: CodeInterpreterCompatibility | null;
};

/**
 * No model-name heuristics here on purpose: an unseen model is treated as
 * usable, and only recorded evidence removes it from the picker.
 */
export function modelSupportsCodeInterpreter(m?: CodeInterpreterModelRef): boolean {
  if (!m) return false;
  const info = m.code_interpreter;
  if (!info) return true;
  if (typeof info.selectable === "boolean") return info.selectable;
  return info.status !== "incompatible" && info.status !== "degraded";
}

export function isVerifiedCodeInterpreterModel(m?: CodeInterpreterModelRef): boolean {
  return Boolean(m?.code_interpreter?.status === "compatible");
}

export function codeInterpreterBlockedReason(
  m?: CodeInterpreterModelRef,
): string | null {
  if (!m || modelSupportsCodeInterpreter(m)) return null;
  return (
    m.code_interpreter?.reason_detail?.trim() ||
    "This model is currently blocked for Code Interpreter."
  );
}

export function filterCodeInterpreterModels<T extends CodeInterpreterModelRef>(
  models: T[],
): T[] {
  return models.filter((m) => modelSupportsCodeInterpreter(m));
}

/** Prefer a verified model, then Auto Router, then any non-blocked model. */
export function findCodeInterpreterFallbackModel<T extends CodeInterpreterModelRef>(
  models: T[],
): T | undefined {
  const verified = models.find(
    (m) => !isAutoRouterModel(m) && isVerifiedCodeInterpreterModel(m),
  );
  if (verified) return verified;
  const autoRouter = models.find(
    (m) => isAutoRouterModel(m) && modelSupportsCodeInterpreter(m),
  );
  if (autoRouter) return autoRouter;
  return models.find((m) => modelSupportsCodeInterpreter(m));
}

/** Keep the user's model unless evidence blocks it for this tool. */
export function resolveCodeInterpreterModel<T extends CodeInterpreterModelRef>(
  models: T[],
  candidate: T | undefined,
): T | undefined {
  if (candidate && modelSupportsCodeInterpreter(candidate)) return candidate;
  return findCodeInterpreterFallbackModel(models) ?? candidate;
}
