/** Speech-capable chat model detection for Text-to-Speech tool. */
import { AUTO_ROUTER_EXTERNAL_ID, isAutoRouterModel, } from "./chatModels";
function dedicatedTextToSpeech(m) {
    return Boolean(m.supports_text_to_speech || m.is_speech_model);
}
function autoRouterCanGenerateSpeech(catalog) {
    return Boolean(catalog?.length && findConcreteSpeechGenerationModel(catalog));
}
export function modelSupportsTextToSpeech(m, catalog) {
    if (!m)
        return false;
    if (isAutoRouterModel(m))
        return autoRouterCanGenerateSpeech(catalog);
    return dedicatedTextToSpeech(m);
}
export function modelSupportsSpeech(m, catalog) {
    return modelSupportsTextToSpeech(m, catalog);
}
export function findConcreteSpeechGenerationModel(models) {
    return models.find((m) => !isAutoRouterModel(m) && dedicatedTextToSpeech(m));
}
export function findSpeechGenerationFallbackModel(models) {
    const autoRouter = models.find(isAutoRouterModel);
    if (autoRouter && autoRouterCanGenerateSpeech(models))
        return autoRouter;
    return findConcreteSpeechGenerationModel(models);
}
export function resolveSpeechGenerationModel(models, candidate) {
    if (isAutoRouterModel(candidate)) {
        if (autoRouterCanGenerateSpeech(models))
            return candidate;
        const fallback = findConcreteSpeechGenerationModel(models);
        return fallback ?? candidate;
    }
    if (modelSupportsSpeech(candidate, models))
        return candidate;
    const fallback = findConcreteSpeechGenerationModel(models);
    return fallback ?? candidate;
}
/** Prefer a catalog voice; remap stale OpenAI defaults like "alloy". */
export function resolveSpeechVoiceForModel(model, currentVoice) {
    const voices = (model?.supported_voices || [])
        .map((v) => String(v || "").trim())
        .filter(Boolean);
    const current = (currentVoice || "").trim();
    if (voices.length) {
        if (current && voices.includes(current))
            return current;
        return voices[0];
    }
    return current || "alloy";
}
function findModelByStoredId(models, stored) {
    const id = stored.trim();
    if (!id)
        return undefined;
    return models.find((m) => m.id === id) ?? models.find((m) => m.external_id === id);
}
export function resolveSessionModelForSpeechTools(models, sessionModel, speechGenerationEnabled, fallbackToDefault) {
    const stored = (sessionModel || "").trim();
    if (speechGenerationEnabled && models.length) {
        const current = stored ? findModelByStoredId(models, stored) : undefined;
        if (current && modelSupportsSpeech(current, models)) {
            return current.id;
        }
        const speechModel = findSpeechGenerationFallbackModel(models) ?? findConcreteSpeechGenerationModel(models);
        if (speechModel)
            return speechModel.id;
    }
    if (stored) {
        if (!models.length)
            return stored;
        const match = findModelByStoredId(models, stored);
        if (match)
            return match.id;
        return stored;
    }
    return fallbackToDefault(undefined);
}
export { AUTO_ROUTER_EXTERNAL_ID, isAutoRouterModel };
