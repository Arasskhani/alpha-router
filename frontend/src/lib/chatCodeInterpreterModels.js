/** Code Interpreter model compatibility, driven only by backend evidence. */
import { isAutoRouterModel } from "./chatModels";
/**
 * No model-name heuristics here on purpose: an unseen model is treated as
 * usable, and only recorded evidence removes it from the picker.
 */
export function modelSupportsCodeInterpreter(m) {
    if (!m)
        return false;
    const info = m.code_interpreter;
    if (!info)
        return true;
    if (typeof info.selectable === "boolean")
        return info.selectable;
    return info.status !== "incompatible" && info.status !== "degraded";
}
export function isVerifiedCodeInterpreterModel(m) {
    return Boolean(m?.code_interpreter?.status === "compatible");
}
export function codeInterpreterBlockedReason(m) {
    if (!m || modelSupportsCodeInterpreter(m))
        return null;
    return (m.code_interpreter?.reason_detail?.trim() ||
        "This model is currently blocked for Code Interpreter.");
}
export function filterCodeInterpreterModels(models) {
    return models.filter((m) => modelSupportsCodeInterpreter(m));
}
/** Prefer a verified model, then Auto Router, then any non-blocked model. */
export function findCodeInterpreterFallbackModel(models) {
    const verified = models.find((m) => !isAutoRouterModel(m) && isVerifiedCodeInterpreterModel(m));
    if (verified)
        return verified;
    const autoRouter = models.find((m) => isAutoRouterModel(m) && modelSupportsCodeInterpreter(m));
    if (autoRouter)
        return autoRouter;
    return models.find((m) => modelSupportsCodeInterpreter(m));
}
/** Keep the user's model unless evidence blocks it for this tool. */
export function resolveCodeInterpreterModel(models, candidate) {
    if (candidate && modelSupportsCodeInterpreter(candidate))
        return candidate;
    return findCodeInterpreterFallbackModel(models) ?? candidate;
}
