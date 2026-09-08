import { STORAGE_KEYS } from "./brand";
import { DEFAULT_CUSTOM_ASPECT_RATIO, DEFAULT_IMAGE_ASPECT_PRESET, aspectRatioFromLegacySize, normalizeCustomAspectRatio, normalizeImageAspectPreset, } from "./imageSize";
/** All tools off — used for new chats and reset. */
export const FRESH_CHAT_TOOLS = {
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
export function copyFreshChatTools() {
    return { ...FRESH_CHAT_TOOLS };
}
export function anyChatToolEnabled(tools) {
    return (tools.webSearch ||
        tools.webFetch ||
        tools.imageGeneration ||
        tools.videoGeneration ||
        tools.speechGeneration ||
        tools.codeInterpreter);
}
export const DEFAULT_CHAT_TOOLS = { ...FRESH_CHAT_TOOLS };
function normalizeDepth(v) {
    if (v === "low" || v === "high")
        return v;
    return "medium";
}
function normalizeVideoResolution(v) {
    if (v === "480p" || v === "1080p" || v === "720p")
        return v;
    return "720p";
}
function normalizeVideoDuration(v) {
    const n = Number(v);
    if (!Number.isFinite(n))
        return FRESH_CHAT_TOOLS.videoDuration;
    const rounded = Math.round(n);
    return rounded >= 1 ? rounded : FRESH_CHAT_TOOLS.videoDuration;
}
export function videoDurationChoices(supported) {
    if (!supported?.length)
        return [];
    const out = [];
    const seen = new Set();
    for (const raw of supported) {
        const parsed = Number(raw);
        if (!Number.isFinite(parsed))
            continue;
        const seconds = Math.round(parsed);
        if (seconds < 1 || seen.has(seconds))
            continue;
        seen.add(seconds);
        out.push(seconds);
    }
    return out;
}
export function isAllowedVideoDuration(duration, supported) {
    const choices = videoDurationChoices(supported);
    const selected = Number(duration);
    if (!Number.isFinite(selected) || selected < 1)
        return false;
    if (!choices.length)
        return true;
    return choices.includes(Math.round(selected));
}
function normalizeVideoAspectRatio(v) {
    const raw = (v || "").trim();
    if (["16:9", "9:16", "1:1", "3:2", "2:3", "4:3", "3:4"].includes(raw))
        return raw;
    return "16:9";
}
function normalizeSpeechFormat(_v) {
    return "mp3";
}
function normalizeSpeechVoice(v) {
    const raw = (v || "").trim();
    return raw || "alloy";
}
function normalizeSpeechSpeed(v) {
    const n = Number(v);
    if (!Number.isFinite(n))
        return 1.0;
    return Math.max(0.25, Math.min(4.0, n));
}
export function normalizeChatTools(raw) {
    if (!raw)
        return { ...FRESH_CHAT_TOOLS };
    const legacySize = raw.imageCustomSize;
    const customAspect = normalizeCustomAspectRatio(raw.imageCustomAspectRatio) ??
        aspectRatioFromLegacySize(legacySize);
    let imageGeneration = raw.imageGeneration ?? FRESH_CHAT_TOOLS.imageGeneration;
    let videoGeneration = raw.videoGeneration ?? FRESH_CHAT_TOOLS.videoGeneration;
    let speechGeneration = raw.speechGeneration ?? FRESH_CHAT_TOOLS.speechGeneration;
    // Mutual exclusion: only one media generation tool can be on at a time.
    // Priority: speech > video > image when multiple are explicitly set.
    if (speechGeneration) {
        imageGeneration = false;
        videoGeneration = false;
    }
    else if (videoGeneration) {
        imageGeneration = false;
    }
    return {
        webSearch: raw.webSearch ?? FRESH_CHAT_TOOLS.webSearch,
        webSearchDepth: normalizeDepth(raw.webSearchDepth),
        webFetch: raw.webFetch ?? FRESH_CHAT_TOOLS.webFetch,
        imageGeneration,
        imageAspectRatio: normalizeImageAspectPreset(raw.imageAspectRatio),
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
export function loadChatTools() {
    try {
        const raw = localStorage.getItem(STORAGE_KEYS.chatTools);
        if (!raw)
            return { ...FRESH_CHAT_TOOLS };
        return normalizeChatTools(JSON.parse(raw));
    }
    catch {
        return { ...FRESH_CHAT_TOOLS };
    }
}
export function toolsToApiPayload(state) {
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
export function webSearchDepthLabel(depth) {
    if (depth === "low")
        return "Low";
    if (depth === "high")
        return "High";
    return "Medium";
}
