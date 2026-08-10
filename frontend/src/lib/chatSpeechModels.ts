/** Speech-capable chat model detection for Text-to-Speech tool. */

import {
  AUTO_ROUTER_EXTERNAL_ID,
  isAutoRouterModel,
  type ChatModelRef,
} from "./chatModels";

export type SpeechCapableModelRef = ChatModelRef & {
  is_speech_model?: boolean;
  supports_text_to_speech?: boolean;
  supported_voices?: string[];
  supported_formats?: string[];
  supported_speeds?: [number, number] | number[];
  max_text_length?: number;
};

function dedicatedTextToSpeech(m: SpeechCapableModelRef): boolean {
  return Boolean(m.supports_text_to_speech || m.is_speech_model);
}

function autoRouterCanGenerateSpeech(catalog?: SpeechCapableModelRef[]): boolean {
  return Boolean(catalog?.length && findConcreteSpeechGenerationModel(catalog));
}

export function modelSupportsTextToSpeech(
  m?: SpeechCapableModelRef,
  catalog?: SpeechCapableModelRef[],
): boolean {
  if (!m) return false;
  if (isAutoRouterModel(m)) return autoRouterCanGenerateSpeech(catalog);
  return dedicatedTextToSpeech(m);
}

export function modelSupportsSpeech(
  m?: SpeechCapableModelRef,
  catalog?: SpeechCapableModelRef[],
): boolean {
  return modelSupportsTextToSpeech(m, catalog);
}

export function findConcreteSpeechGenerationModel<T extends SpeechCapableModelRef>(
  models: T[],
): T | undefined {
  return models.find((m) => !isAutoRouterModel(m) && dedicatedTextToSpeech(m));
}

export function findSpeechGenerationFallbackModel<T extends SpeechCapableModelRef>(
  models: T[],
): T | undefined {
  const autoRouter = models.find(isAutoRouterModel);
  if (autoRouter && autoRouterCanGenerateSpeech(models)) return autoRouter;
  return findConcreteSpeechGenerationModel(models);
}

export function resolveSpeechGenerationModel<T extends SpeechCapableModelRef>(
  models: T[],
  candidate: T,
): T {
  if (isAutoRouterModel(candidate)) {
    if (autoRouterCanGenerateSpeech(models)) return candidate;
    const fallback = findConcreteSpeechGenerationModel(models);
    return fallback ?? candidate;
  }
  if (modelSupportsSpeech(candidate, models)) return candidate;
  const fallback = findConcreteSpeechGenerationModel(models);
  return fallback ?? candidate;
}

/** Prefer a catalog voice; remap stale OpenAI defaults like "alloy". */
export function resolveSpeechVoiceForModel(
  model: SpeechCapableModelRef | undefined,
  currentVoice?: string | null,
): string {
  const voices = (model?.supported_voices || [])
    .map((v) => String(v || "").trim())
    .filter(Boolean);
  const current = (currentVoice || "").trim();
  if (voices.length) {
    if (current && voices.includes(current)) return current;
    return voices[0];
  }
  return current || "alloy";
}

function findModelByStoredId<T extends SpeechCapableModelRef>(
  models: T[],
  stored: string,
): T | undefined {
  const id = stored.trim();
  if (!id) return undefined;
  return models.find((m) => m.id === id) ?? models.find((m) => m.external_id === id);
}

export function resolveSessionModelForSpeechTools<T extends SpeechCapableModelRef>(
  models: T[],
  sessionModel: string | undefined,
  speechGenerationEnabled: boolean,
  fallbackToDefault: (current?: string) => string,
): string {
  const stored = (sessionModel || "").trim();
  if (speechGenerationEnabled && models.length) {
    const current = stored ? findModelByStoredId(models, stored) : undefined;
    if (current && modelSupportsSpeech(current, models)) {
      return current.id;
    }
    const speechModel =
      findSpeechGenerationFallbackModel(models) ?? findConcreteSpeechGenerationModel(models);
    if (speechModel) return speechModel.id;
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
