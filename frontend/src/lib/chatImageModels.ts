/** Image-capable chat model detection and preferred model selection for Image Generation tool. */

import {
  AUTO_ROUTER_EXTERNAL_ID,
  isAutoRouterModel,
  type ChatModelRef,
} from "./chatModels";

export type ImageCapableModelRef = ChatModelRef & {
  is_image_model?: boolean;
  supports_text_to_image?: boolean;
  supports_image_to_image?: boolean;
  /** Capabilities this model is the admin-chosen system default for. */
  default_kinds?: string[];
};

/** The admin-chosen default for a capability, when it is still usable. */
export function findSystemDefaultModel<T extends { default_kinds?: string[] }>(
  models: T[],
  kind: string,
  usable: (m: T) => boolean,
): T | undefined {
  const picked = models.find((m) => (m.default_kinds || []).includes(kind));
  return picked && usable(picked) ? picked : undefined;
}

const IMAGE_ID_HINTS = [
  "nanobanana",
  "image",
  "dall-e",
  "dalle",
  "flux",
  "sdxl",
  "stable-diffusion",
] as const;

function isImageModelIdHeuristic(modelId: string, modelName?: string): boolean {
  const v = `${modelId} ${modelName || ""}`.toLowerCase();
  return IMAGE_ID_HINTS.some((hint) => v.includes(hint));
}

function dedicatedTextToImage(m: ImageCapableModelRef): boolean {
  if (m.supports_text_to_image) return true;
  if (m.is_image_model) return true;
  return isImageModelIdHeuristic(m.external_id || m.id, m.name);
}

function dedicatedImageToImage(m: ImageCapableModelRef): boolean {
  if (m.supports_image_to_image) return true;
  const v = `${m.external_id || m.id} ${m.name || ""}`.toLowerCase();
  if (v.includes("gemini") && v.includes("image")) return true;
  return (
    v.includes("kontext") ||
    v.includes("img2img") ||
    v.includes("image-to-image")
  );
}

function autoRouterCanGenerateImages(catalog?: ImageCapableModelRef[]): boolean {
  return Boolean(catalog?.length && findConcreteImageGenerationModel(catalog));
}

/** Auto Router only when the catalog has a concrete image model on the same connection. */
export function modelSupportsTextToImage(
  m?: ImageCapableModelRef,
  catalog?: ImageCapableModelRef[],
): boolean {
  if (!m) return false;
  if (isAutoRouterModel(m)) return autoRouterCanGenerateImages(catalog);
  return dedicatedTextToImage(m);
}

export function modelSupportsImageToImage(
  m?: ImageCapableModelRef,
  catalog?: ImageCapableModelRef[],
): boolean {
  if (!m) return false;
  if (isAutoRouterModel(m)) return autoRouterCanGenerateImages(catalog);
  return dedicatedImageToImage(m);
}

export function modelSupportsImages(
  m?: ImageCapableModelRef,
  catalog?: ImageCapableModelRef[],
): boolean {
  if (!m) return false;
  if (isAutoRouterModel(m)) return autoRouterCanGenerateImages(catalog);
  return dedicatedTextToImage(m) || dedicatedImageToImage(m);
}

export function findImageGenerationFallbackModel<T extends ImageCapableModelRef>(
  models: T[],
): T | undefined {
  const autoRouter = models.find(isAutoRouterModel);
  if (autoRouter && autoRouterCanGenerateImages(models)) return autoRouter;
  return findConcreteImageGenerationModel(models);
}

/** First enabled image model excluding Auto Router (for upstream image API calls). */
export function findConcreteImageGenerationModel<T extends ImageCapableModelRef>(
  models: T[],
): T | undefined {
  // Admin's pick wins over catalog order, which is otherwise arbitrary.
  const chosen = findSystemDefaultModel(
    models,
    "image",
    (m) => !isAutoRouterModel(m) && modelSupportsImages(m, models),
  );
  if (chosen) return chosen;
  return models.find((m) => !isAutoRouterModel(m) && modelSupportsImages(m, models));
}

/** Keep UI model; only substitute when the selected model cannot generate images. */
export function resolveImageGenerationModel<T extends ImageCapableModelRef>(
  models: T[],
  candidate: T,
): T {
  if (isAutoRouterModel(candidate)) {
    if (autoRouterCanGenerateImages(models)) return candidate;
    const fallback = findConcreteImageGenerationModel(models);
    return fallback ?? candidate;
  }
  if (modelSupportsImages(candidate, models)) return candidate;
  const fallback = findConcreteImageGenerationModel(models);
  return fallback ?? candidate;
}

function findModelByStoredId<T extends ImageCapableModelRef>(
  models: T[],
  stored: string,
): T | undefined {
  const id = stored.trim();
  if (!id) return undefined;
  return models.find((m) => m.id === id) ?? models.find((m) => m.external_id === id);
}

/**
 * Session model for UI + persistence — honors Image Generation tool state after reload.
 *
 * A non-empty per-chat `sessionModel` is never replaced by the user/global default.
 * Fallback is only used when the session has no model yet. While the catalog is still
 * empty, the stored session model is kept as-is so hydrate cannot wipe it.
 */
export function resolveSessionModelForTools<T extends ImageCapableModelRef>(
  models: T[],
  sessionModel: string | undefined,
  imageGenerationEnabled: boolean,
  fallbackToDefault: (current?: string) => string,
): string {
  const stored = (sessionModel || "").trim();
  if (imageGenerationEnabled && models.length) {
    const current = stored ? findModelByStoredId(models, stored) : undefined;
    if (current && modelSupportsImages(current, models)) {
      return current.id;
    }
    const imageModel =
      findImageGenerationFallbackModel(models) ?? findConcreteImageGenerationModel(models);
    if (imageModel) return imageModel.id;
  }
  if (stored) {
    if (!models.length) return stored;
    const match = findModelByStoredId(models, stored);
    if (match) return match.id;
    // Catalog loaded but id unknown (stale) — keep the per-chat choice; do not force default.
    return stored;
  }
  return fallbackToDefault(undefined);
}

export { AUTO_ROUTER_EXTERNAL_ID, isAutoRouterModel };
