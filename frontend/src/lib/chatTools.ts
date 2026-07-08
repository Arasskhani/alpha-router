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
    tools.codeInterpreter
  );
}



export const DEFAULT_CHAT_TOOLS: ChatToolsState = { ...FRESH_CHAT_TOOLS };



function normalizeDepth(v: string | undefined): WebSearchDepth {

  if (v === "low" || v === "high") return v;

  return "medium";

}



export function normalizeChatTools(raw?: Partial<ChatToolsState> | null): ChatToolsState {

  if (!raw) return { ...FRESH_CHAT_TOOLS };

  const legacySize = (raw as Partial<ChatToolsState>).imageCustomSize;
  const customAspect =
    normalizeCustomAspectRatio((raw as Partial<ChatToolsState>).imageCustomAspectRatio) ??
    aspectRatioFromLegacySize(legacySize);

  return {
    webSearch: raw.webSearch ?? FRESH_CHAT_TOOLS.webSearch,
    webSearchDepth: normalizeDepth(raw.webSearchDepth),
    webFetch: raw.webFetch ?? FRESH_CHAT_TOOLS.webFetch,
    imageGeneration: raw.imageGeneration ?? FRESH_CHAT_TOOLS.imageGeneration,
    imageAspectRatio: normalizeImageAspectPreset(
      (raw as Partial<ChatToolsState>).imageAspectRatio,
    ),
    imageCustomAspectRatio: customAspect ?? FRESH_CHAT_TOOLS.imageCustomAspectRatio,
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

      code_interpreter: state.codeInterpreter,

    },

  };

}



export function webSearchDepthLabel(depth: WebSearchDepth) {

  if (depth === "low") return "Low";

  if (depth === "high") return "High";

  return "Medium";

}


