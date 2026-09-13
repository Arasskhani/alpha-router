/** Video-capable chat model detection for Video Generation tool. */

import {
  AUTO_ROUTER_EXTERNAL_ID,
  isAutoRouterModel,
  type ChatModelRef,
} from "./chatModels";

export type VideoCapableModelRef = ChatModelRef & {
  is_video_model?: boolean;
  supports_text_to_video?: boolean;
  supports_image_to_video?: boolean;
  /** Capabilities this model is the admin-chosen system default for. */
  default_kinds?: string[];
};

function dedicatedTextToVideo(m: VideoCapableModelRef): boolean {
  return Boolean(m.supports_text_to_video || m.is_video_model);
}

function dedicatedImageToVideo(m: VideoCapableModelRef): boolean {
  return Boolean(m.supports_image_to_video);
}

function autoRouterCanGenerateVideos(catalog?: VideoCapableModelRef[]): boolean {
  return Boolean(catalog?.length && findConcreteVideoGenerationModel(catalog));
}

export function modelSupportsTextToVideo(
  m?: VideoCapableModelRef,
  catalog?: VideoCapableModelRef[],
): boolean {
  if (!m) return false;
  if (isAutoRouterModel(m)) return autoRouterCanGenerateVideos(catalog);
  return dedicatedTextToVideo(m);
}

export function modelSupportsImageToVideo(
  m?: VideoCapableModelRef,
  catalog?: VideoCapableModelRef[],
): boolean {
  if (!m) return false;
  if (isAutoRouterModel(m)) return autoRouterCanGenerateVideos(catalog);
  return dedicatedImageToVideo(m);
}

export function modelSupportsVideos(
  m?: VideoCapableModelRef,
  catalog?: VideoCapableModelRef[],
): boolean {
  if (!m) return false;
  if (isAutoRouterModel(m)) return autoRouterCanGenerateVideos(catalog);
  return dedicatedTextToVideo(m) || dedicatedImageToVideo(m);
}

export function findConcreteVideoGenerationModel<T extends VideoCapableModelRef>(
  models: T[],
): T | undefined {
  // Admin's pick wins over catalog order, which is otherwise arbitrary.
  const chosen = models.find((m) => (m.default_kinds || []).includes("video"));
  if (chosen && !isAutoRouterModel(chosen) && modelSupportsVideos(chosen, models)) {
    return chosen;
  }
  return models.find((m) => !isAutoRouterModel(m) && modelSupportsVideos(m, models));
}

export function findVideoGenerationFallbackModel<T extends VideoCapableModelRef>(
  models: T[],
): T | undefined {
  const autoRouter = models.find(isAutoRouterModel);
  if (autoRouter && autoRouterCanGenerateVideos(models)) return autoRouter;
  return findConcreteVideoGenerationModel(models);
}

export function resolveVideoGenerationModel<T extends VideoCapableModelRef>(
  models: T[],
  candidate: T,
): T {
  if (isAutoRouterModel(candidate)) {
    if (autoRouterCanGenerateVideos(models)) return candidate;
    const fallback = findConcreteVideoGenerationModel(models);
    return fallback ?? candidate;
  }
  if (modelSupportsVideos(candidate, models)) return candidate;
  const fallback = findConcreteVideoGenerationModel(models);
  return fallback ?? candidate;
}

function findModelByStoredId<T extends VideoCapableModelRef>(
  models: T[],
  stored: string,
): T | undefined {
  const id = stored.trim();
  if (!id) return undefined;
  return models.find((m) => m.id === id) ?? models.find((m) => m.external_id === id);
}

export function resolveSessionModelForVideoTools<T extends VideoCapableModelRef>(
  models: T[],
  sessionModel: string | undefined,
  videoGenerationEnabled: boolean,
  fallbackToDefault: (current?: string) => string,
): string {
  const stored = (sessionModel || "").trim();
  if (videoGenerationEnabled && models.length) {
    const current = stored ? findModelByStoredId(models, stored) : undefined;
    if (current && modelSupportsVideos(current, models)) {
      return current.id;
    }
    const videoModel =
      findVideoGenerationFallbackModel(models) ?? findConcreteVideoGenerationModel(models);
    if (videoModel) return videoModel.id;
  }
  if (stored) {
    if (!models.length) return stored;
    const match = findModelByStoredId(models, stored);
    if (match) return match.id;
    return stored;
  }
  return fallbackToDefault(undefined);
}

export { AUTO_ROUTER_EXTERNAL_ID, isAutoRouterModel };
