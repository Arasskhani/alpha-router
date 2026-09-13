/** Video-capable chat model detection for Video Generation tool. */
import { AUTO_ROUTER_EXTERNAL_ID, isAutoRouterModel, } from "./chatModels";
function dedicatedTextToVideo(m) {
    return Boolean(m.supports_text_to_video || m.is_video_model);
}
function dedicatedImageToVideo(m) {
    return Boolean(m.supports_image_to_video);
}
function autoRouterCanGenerateVideos(catalog) {
    return Boolean(catalog?.length && findConcreteVideoGenerationModel(catalog));
}
export function modelSupportsTextToVideo(m, catalog) {
    if (!m)
        return false;
    if (isAutoRouterModel(m))
        return autoRouterCanGenerateVideos(catalog);
    return dedicatedTextToVideo(m);
}
export function modelSupportsImageToVideo(m, catalog) {
    if (!m)
        return false;
    if (isAutoRouterModel(m))
        return autoRouterCanGenerateVideos(catalog);
    return dedicatedImageToVideo(m);
}
export function modelSupportsVideos(m, catalog) {
    if (!m)
        return false;
    if (isAutoRouterModel(m))
        return autoRouterCanGenerateVideos(catalog);
    return dedicatedTextToVideo(m) || dedicatedImageToVideo(m);
}
export function findConcreteVideoGenerationModel(models) {
    // Admin's pick wins over catalog order, which is otherwise arbitrary.
    const chosen = models.find((m) => (m.default_kinds || []).includes("video"));
    if (chosen && !isAutoRouterModel(chosen) && modelSupportsVideos(chosen, models)) {
        return chosen;
    }
    return models.find((m) => !isAutoRouterModel(m) && modelSupportsVideos(m, models));
}
export function findVideoGenerationFallbackModel(models) {
    const autoRouter = models.find(isAutoRouterModel);
    if (autoRouter && autoRouterCanGenerateVideos(models))
        return autoRouter;
    return findConcreteVideoGenerationModel(models);
}
export function resolveVideoGenerationModel(models, candidate) {
    if (isAutoRouterModel(candidate)) {
        if (autoRouterCanGenerateVideos(models))
            return candidate;
        const fallback = findConcreteVideoGenerationModel(models);
        return fallback ?? candidate;
    }
    if (modelSupportsVideos(candidate, models))
        return candidate;
    const fallback = findConcreteVideoGenerationModel(models);
    return fallback ?? candidate;
}
function findModelByStoredId(models, stored) {
    const id = stored.trim();
    if (!id)
        return undefined;
    return models.find((m) => m.id === id) ?? models.find((m) => m.external_id === id);
}
export function resolveSessionModelForVideoTools(models, sessionModel, videoGenerationEnabled, fallbackToDefault) {
    const stored = (sessionModel || "").trim();
    if (videoGenerationEnabled && models.length) {
        const current = stored ? findModelByStoredId(models, stored) : undefined;
        if (current && modelSupportsVideos(current, models)) {
            return current.id;
        }
        const videoModel = findVideoGenerationFallbackModel(models) ?? findConcreteVideoGenerationModel(models);
        if (videoModel)
            return videoModel.id;
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
