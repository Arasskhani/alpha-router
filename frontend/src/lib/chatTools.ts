import { STORAGE_KEYS } from "./brand";

import {
  DEFAULT_CUSTOM_ASPECT_RATIO,
  DEFAULT_IMAGE_ASPECT_PRESET,
  aspectRatioFromLegacySize,
  normalizeCustomAspectRatio,
  normalizeImageAspectPreset,
  type ImageAspectPresetId,
} from "./imageSize";

export type WebSearchDepth = "low" | "medium" | "high";
export type VideoResolution = "480p" | "720p" | "1080p";
export type SpeechFormat = "mp3";

export type ChatToolsState = {
  webSearch: boolean;
  webSearchDepth: WebSearchDepth;
  webFetch: boolean;
  imageGeneration: boolean;
  /** Aspect ratio preset for Image Generation tool (per chat session). */
  imageAspectRatio: ImageAspectPresetId;
  /** W:H when imageAspectRatio is "custom" (e.g. 21:9). */
  imageCustomAspectRatio: string;
  /** @deprecated legacy WxH — migrated to imageCustomAspectRatio on load. */
  imageCustomSize?: string;
  videoGeneration: boolean;
  videoDuration: number;
  videoResolution: VideoResolution;
  videoAspectRatio: string;
  videoGenerateAudio: boolean;
  speechGeneration: boolean;
  speechVoice: string;
  speechFormat: SpeechFormat;
  speechSpeed: number;
  codeInterpreter: boolean;
};

/** All tools off — used for new chats and reset. */
export const FRESH_CHAT_TOOLS: ChatToolsState = {
  webSearch: false,
  webSearchDepth: "medium",
  webFetch: false,
  imageGeneration: false,
  imageAspectRatio: DEFAULT_IMAGE_ASPECT_PRESET,
  imageCustomAspectRatio: DEFAULT_CUSTOM_ASPECT_RATIO,
  videoGeneration: false,
  videoDuration: 4,
  videoResolution: "720p",
  videoAspectRatio: "16:9",
  videoGenerateAudio: false,
  speechGeneration: false,
  speechVoice: "alloy",
  speechFormat: "mp3",
  speechSpeed: 1.0,
  codeInterpreter: false,
};

export function copyFreshChatTools(): ChatToolsState {
  return { ...FRESH_CHAT_TOOLS };
}

export function anyChatToolEnabled(tools: ChatToolsState): boolean {
  return (
    tools.webSearch ||
    tools.webFetch ||
    tools.imageGeneration ||
    tools.videoGeneration ||
    tools.speechGeneration ||
    tools.codeInterpreter
  );
}

export const DEFAULT_CHAT_TOOLS: ChatToolsState = { ...FRESH_CHAT_TOOLS };

function normalizeDepth(v: string | undefined): WebSearchDepth {
  if (v === "low" || v === "high") return v;
  return "medium";
}

function normalizeVideoResolution(v: string | undefined): VideoResolution {
  if (v === "480p" || v === "1080p" || v === "720p") return v;
  return "720p";
}

function normalizeVideoDuration(v: number | undefined): number {
  const n = Number(v);
  if (!Number.isFinite(n)) return FRESH_CHAT_TOOLS.videoDuration;
  const rounded = Math.round(n);
  return rounded >= 1 ? rounded : FRESH_CHAT_TOOLS.videoDuration;
}

export function videoDurationChoices(supported?: number[] | null): number[] {
  if (!supported?.length) return [];
  const out: number[] = [];
  const seen = new Set<number>();
  for (const raw of supported) {
    const parsed = Number(raw);
    if (!Number.isFinite(parsed)) continue;
    const seconds = Math.round(parsed);
    if (seconds < 1 || seen.has(seconds)) continue;
    seen.add(seconds);
    out.push(seconds);
  }
  return out;
}

export function isAllowedVideoDuration(
  duration: number | undefined,
  supported?: number[] | null,
): boolean {
  const choices = videoDurationChoices(supported);
  const selected = Number(duration);
  if (!Number.isFinite(selected) || selected < 1) return false;
  if (!choices.length) return true;
  return choices.includes(Math.round(selected));
}

function normalizeVideoAspectRatio(v: string | undefined): string {
  const raw = (v || "").trim();
  if (["16:9", "9:16", "1:1", "3:2", "2:3", "4:3", "3:4"].includes(raw)) return raw;
  return "16:9";
}

function normalizeSpeechFormat(_v: string | undefined): SpeechFormat {
  return "mp3";
}

function normalizeSpeechVoice(v: string | undefined): string {
  const raw = (v || "").trim();
  return raw || "alloy";
}

function normalizeSpeechSpeed(v: number | undefined): number {
  const n = Number(v);
  if (!Number.isFinite(n)) return 1.0;
  return Math.max(0.25, Math.min(4.0, n));
}

export function normalizeChatTools(raw?: Partial<ChatToolsState> | null): ChatToolsState {
  if (!raw) return { ...FRESH_CHAT_TOOLS };

  const legacySize = (raw as Partial<ChatToolsState>).imageCustomSize;
  const customAspect =
    normalizeCustomAspectRatio((raw as Partial<ChatToolsState>).imageCustomAspectRatio) ??
    aspectRatioFromLegacySize(legacySize);

  let imageGeneration = raw.imageGeneration ?? FRESH_CHAT_TOOLS.imageGeneration;
  let videoGeneration = raw.videoGeneration ?? FRESH_CHAT_TOOLS.videoGeneration;
  let speechGeneration = raw.speechGeneration ?? FRESH_CHAT_TOOLS.speechGeneration;
  // Mutual exclusion: only one media generation tool can be on at a time.
  // Priority: speech > video > image when multiple are explicitly set.
  if (speechGeneration) {
    imageGeneration = false;
    videoGeneration = false;
  } else if (videoGeneration) {
    imageGeneration = false;
  }

  return {
    webSearch: raw.webSearch ?? FRESH_CHAT_TOOLS.webSearch,
    webSearchDepth: normalizeDepth(raw.webSearchDepth),
    webFetch: raw.webFetch ?? FRESH_CHAT_TOOLS.webFetch,
    imageGeneration,
    imageAspectRatio: normalizeImageAspectPreset(
      (raw as Partial<ChatToolsState>).imageAspectRatio,
    ),
    imageCustomAspectRatio: customAspect ?? FRESH_CHAT_TOOLS.imageCustomAspectRatio,
    videoGeneration,
    videoDuration: normalizeVideoDuration(raw.videoDuration),
    videoResolution: normalizeVideoResolution(raw.videoResolution),
    videoAspectRatio: normalizeVideoAspectRatio(raw.videoAspectRatio),
    videoGenerateAudio: raw.videoGenerateAudio ?? FRESH_CHAT_TOOLS.videoGenerateAudio,
    speechGeneration,
    speechVoice: normalizeSpeechVoice(raw.speechVoice),
    speechFormat: normalizeSpeechFormat(raw.speechFormat),
    speechSpeed: normalizeSpeechSpeed(raw.speechSpeed),
    codeInterpreter: raw.codeInterpreter ?? FRESH_CHAT_TOOLS.codeInterpreter,
  };
}

/** @deprecated Global tools prefs; sessions store their own tools now. */
export function loadChatTools(): ChatToolsState {
  try {
    const raw = localStorage.getItem(STORAGE_KEYS.chatTools);
    if (!raw) return { ...FRESH_CHAT_TOOLS };
    return normalizeChatTools(JSON.parse(raw) as Partial<ChatToolsState>);
  } catch {
    return { ...FRESH_CHAT_TOOLS };
  }
}

export function toolsToApiPayload(state: ChatToolsState) {
  return {
    web_search: state.webSearch,
    tools: {
      web_search: state.webSearch,
      web_search_depth: state.webSearchDepth,
      web_fetch: state.webFetch,
      image_generation: state.imageGeneration,
      video_generation: state.videoGeneration,
      speech_generation: state.speechGeneration,
      code_interpreter: state.codeInterpreter,
    },
  };
}

export function webSearchDepthLabel(depth: WebSearchDepth) {
  if (depth === "low") return "Low";
  if (depth === "high") return "High";
  return "Medium";
}
