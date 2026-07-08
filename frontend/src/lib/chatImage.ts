import {
  type ChatMessage,
  cancelStreamingReplyOnServer,
  fetchSessionMessagesFromServer,
  fetchSessionWithMessages,
  isPrivateChat,
  syncSessionMessages,
} from "./chatStorage";
import { referenceImageFromUserContent, resolveReferenceImageFromUserContent } from "./chatAttachments";
import { isPrivateBlobRef, resolvePrivateMediaUrlForApi } from "./privateMediaStore";
import {
  normalizeImageAspectPreset,
  presetFromAspectRatio,
  resolveImageGeneration,
  resolveRegenerateImageGeneration,
  type ImageAspectPresetId,
} from "./imageSize";

export const IMAGE_PENDING_MARKER = "__NITRO_IMAGE_PENDING__";
export const IMAGE_MESSAGE_PREFIX = "__NITRO_IMAGE_JSON__:";

export type ImagePayload = {
  url: string;
  prompt: string;
  model: string;
  reference_image?: string;
  operation?: "generation" | "img2img";
  /** Stored aspect ratio e.g. 16:9 — used for Regenerate. */
  aspectRatio?: string;
  aspectPreset?: ImageAspectPresetId;
  /** @deprecated legacy WxH from older messages */
  size?: string;
};

type ImageResponse = {
  data?: Array<{ url?: string; b64_json?: string }>;
  size?: string;
  aspect_ratio?: string;
};

/** Must exceed the backend OpenRouter read timeout (180s) so server errors win. */
export const IMAGE_GENERATION_TIMEOUT_MS = 240_000;
export const IMAGE_TIMEOUT_MESSAGE = "Image generation timed out.";

const activeJobs = new Map<string, AbortController>();
const listeners = new Set<(sessionId: string) => void>();

function notify(sessionId: string) {
  listeners.forEach((fn) => {
    try {
      fn(sessionId);
    } catch {
      /* ignore listener errors */
    }
  });
}

export function subscribeBackgroundImageUpdates(listener: (sessionId: string) => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function isBackgroundImageRunning(sessionId: string): boolean {
  return activeJobs.has(sessionId);
}

export function getBackgroundImageSessionIds(): string[] {
  return [...activeJobs.keys()];
}

export function stopBackgroundImageGeneration(sessionId: string) {
  const controller = activeJobs.get(sessionId);
  if (controller) {
    controller.abort();
    activeJobs.delete(sessionId);
  }
}

export function buildImageMessage(payload: ImagePayload): string {
  return `${IMAGE_MESSAGE_PREFIX}${JSON.stringify(payload)}`;
}

export function parseImageMessage(content: string): ImagePayload | null {
  if (!content.startsWith(IMAGE_MESSAGE_PREFIX)) return null;
  try {
    return JSON.parse(content.slice(IMAGE_MESSAGE_PREFIX.length)) as ImagePayload;
  } catch {
    return null;
  }
}

/** Last generated image in the thread (skips pending placeholders). */
export function lastAssistantImageUrl(messages: ChatMessage[]): string | undefined {
  for (let i = messages.length - 1; i >= 0; i -= 1) {
    const msg = messages[i];
    if (msg.role !== "assistant") continue;
    if (msg.content === IMAGE_PENDING_MARKER) continue;
    const payload = parseImageMessage(msg.content);
    const url = payload?.url?.trim();
    if (url) return url;
  }
  return undefined;
}

/**
 * Image-to-image reference: explicit attachment, or prior assistant image when editing.
 */
export function resolveImageGenerationReference(
  userContent: string,
  history: ChatMessage[],
  usePriorAssistantImage = false,
): string | undefined {
  const fromUser = referenceImageFromUserContent(userContent);
  if (fromUser) return fromUser;
  if (usePriorAssistantImage) return lastAssistantImageUrl(history);
  return undefined;
}

/** Async variant — resolves private blob refs for img2img API calls. */
export async function resolveImageGenerationReferenceAsync(
  userContent: string,
  history: ChatMessage[],
  usePriorAssistantImage = false,
): Promise<string | undefined> {
  const fromUser = await resolveReferenceImageFromUserContent(userContent);
  if (fromUser) return fromUser;
  if (!usePriorAssistantImage) return undefined;
  const fromHistory = lastAssistantImageUrl(history);
  if (!fromHistory) return undefined;
  if (isPrivateBlobRef(fromHistory) || fromHistory.startsWith("blob:")) {
    return resolvePrivateMediaUrlForApi(fromHistory);
  }
  return fromHistory;
}

export function sessionHasPendingImage(messages: ChatMessage[]): boolean {
  const last = messages.at(-1);
  return last?.role === "assistant" && last.content === IMAGE_PENDING_MARKER;
}

/** Drop stale pending placeholders superseded by a later assistant message. */
export function stripOrphanImagePending(messages: ChatMessage[]): ChatMessage[] {
  const last = messages.at(-1);
  if (last?.content === IMAGE_PENDING_MARKER) return messages;
  return messages.filter((m) => m.content !== IMAGE_PENDING_MARKER);
}

function lastAssistantContentLen(messages: ChatMessage[]): number {
  const last = messages.at(-1);
  if (!last || last.role !== "assistant") return 0;
  return (last.content || "").length;
}

/** Prefer the copy with more streamed assistant text when server DB lags behind the client. */
export function mergeChatMessagesPreferLocal(
  local: ChatMessage[],
  remote: ChatMessage[],
  inFlight = false,
): ChatMessage[] {
  const cleanedLocal = stripOrphanImagePending(local);
  const cleanedRemote = stripOrphanImagePending(remote);
  if (!cleanedLocal.length) return cleanedRemote;
  if (!cleanedRemote.length) return cleanedLocal;
  if (inFlight && cleanedLocal.length >= cleanedRemote.length) return cleanedLocal;
  if (cleanedLocal.length > cleanedRemote.length) return cleanedLocal;

  const localTailLen = lastAssistantContentLen(cleanedLocal);
  const remoteTailLen = lastAssistantContentLen(cleanedRemote);
  const localLast = cleanedLocal.at(-1);
  const remoteLast = cleanedRemote.at(-1);
  // A locally finalized reply (e.g. "Image generation stopped." after STOP) must
  // not be revived into "generating" by a server copy whose pending marker the
  // cancel request hasn't replaced yet.
  if (
    localLast?.role === "assistant" &&
    localLast.receivedAt != null &&
    remoteLast?.content === IMAGE_PENDING_MARKER &&
    cleanedLocal.length >= cleanedRemote.length
  ) {
    return cleanedLocal;
  }
  if (
    localLast?.role === "assistant" &&
    remoteLast?.role === "assistant" &&
    localLast.receivedAt == null &&
    localTailLen > remoteTailLen
  ) {
    return cleanedLocal;
  }
  if (
    sessionHasIncompleteTextReply(cleanedRemote) &&
    cleanedLocal.length >= cleanedRemote.length &&
    localTailLen >= remoteTailLen
  ) {
    return cleanedLocal;
  }
  return cleanedRemote;
}

export function buildStoppedImageMessages(
  messages: ChatMessage[],
  stoppedText = "Image generation stopped.",
): ChatMessage[] {
  const withoutPending = stripOrphanImagePending(messages.filter((m) => m.content !== IMAGE_PENDING_MARKER));
  const last = withoutPending.at(-1);
  if (last?.role === "assistant" && last.content === stoppedText) return withoutPending;
  return [
    ...withoutPending,
    { role: "assistant", content: stoppedText, receivedAt: Date.now() },
  ];
}

/** True while text stream or image placeholder is still open (server or local). */
export function sessionHasInFlightGeneration(messages: ChatMessage[]): boolean {
  if (sessionHasPendingImage(messages)) return true;
  return sessionHasIncompleteTextReply(messages);
}

/** Assistant text reply still being generated on the server (survives page refresh). */
export function sessionHasIncompleteTextReply(messages: ChatMessage[]): boolean {
  const last = messages.at(-1);
  if (!last || last.role !== "assistant") return false;
  if (last.content === IMAGE_PENDING_MARKER) return false;
  if (parseImageMessage(last.content)) return false;
  if (last.streaming === true) return true;
  return last.receivedAt == null;
}

function parseApiError(raw: string, status: number): string {
  try {
    const j = JSON.parse(raw);
    return j.detail || j.message || raw;
  } catch {
    return raw || `Request failed (${status})`;
  }
}

async function requestImageApi(
  prompt: string,
  modelId: string,
  sessionId: string,
  signal: AbortSignal,
  persist: boolean,
  referenceImage: string | undefined,
  aspectRatio: string | undefined,
  aspectPreset: ImageAspectPresetId,
  sourceSize: string | undefined,
): Promise<ImagePayload> {
  const token = localStorage.getItem("nitro_token");
  const operation = referenceImage ? "img2img" : "generation";
  const resolvedReference = referenceImage
    ? await resolvePrivateMediaUrlForApi(referenceImage)
    : undefined;
  const body: Record<string, unknown> = {
    prompt,
    model: modelId,
    operation,
    reference_image: resolvedReference || null,
    chat_session_id: persist ? sessionId : null,
    persist,
  };
  if (referenceImage && sourceSize) {
    body.size = sourceSize;
  } else if (aspectRatio) {
    body.aspect_ratio = aspectRatio;
  }
  const res = await fetch("/api/images/generate", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(body),
    signal,
  });
  if (!res.ok) throw new Error(parseApiError(await res.text(), res.status));
  const imageResult = (await res.json()) as ImageResponse;
  const first = imageResult?.data?.[0];
  const imageUrl = first?.url || (first?.b64_json ? `data:image/png;base64,${first.b64_json}` : "");
  if (!imageUrl) throw new Error("Image model returned no image URL.");
  const appliedAspect = imageResult.aspect_ratio || aspectRatio;
  const appliedPreset = presetFromAspectRatio(appliedAspect) ?? aspectPreset;
  return {
    url: imageUrl,
    prompt,
    model: modelId,
    aspectRatio: appliedAspect || undefined,
    aspectPreset: appliedPreset,
    size: imageResult.size || sourceSize,
    ...(referenceImage ? { reference_image: referenceImage, operation: "img2img" as const } : { operation: "generation" as const }),
  };
}

/** Runs image generation outside React lifecycle; survives route changes within the SPA. */
export async function runBackgroundImageGeneration(opts: {
  sessionId: string;
  /** Trimmed history for API prompt / reference resolution. */
  historyWithUser: ChatMessage[];
  /** Full local thread for UI sync (matches ChatPanel); defaults to historyWithUser. */
  localMessageBase?: ChatMessage[];
  prompt: string;
  modelId: string;
  privateMode?: boolean;
  referenceImage?: string;
  /** Session default from Chat Tools (ignored when regenerate locks ratio). */
  imageAspectPreset?: ImageAspectPresetId;
  /** Session custom W:H when imageAspectPreset is "custom". */
  imageCustomAspectRatio?: string;
  /** @deprecated legacy WxH */
  imageCustomSize?: string;
  /** Regenerate: keep ratio from prior image message. */
  regenerateFrom?: Pick<ImagePayload, "aspectRatio" | "aspectPreset" | "size">;
  /** When set, pending/final image replace this index instead of appending. */
  replaceIndex?: number;
  fullMessages?: ChatMessage[];
}): Promise<void> {
  const {
    sessionId,
    historyWithUser,
    localMessageBase,
    prompt,
    modelId,
    replaceIndex,
    fullMessages,
    privateMode = false,
    referenceImage,
    imageAspectPreset,
    imageCustomAspectRatio,
    imageCustomSize,
    regenerateFrom,
  } = opts;
  const persist = !privateMode;
  const hasReference = Boolean(referenceImage?.trim());
  const localBase = localMessageBase ?? historyWithUser;
  const syncOpts = { forcePrivate: privateMode };

  const resolved = regenerateFrom
    ? resolveRegenerateImageGeneration({
        prompt,
        payloadAspectRatio: regenerateFrom.aspectRatio,
        payloadPreset: regenerateFrom.aspectPreset,
        payloadSize: regenerateFrom.size,
        sessionPreset: normalizeImageAspectPreset(imageAspectPreset),
        sessionCustomAspect: imageCustomAspectRatio,
        sessionCustomSize: imageCustomSize,
        hasReference,
      })
    : resolveImageGeneration({
        prompt,
        sessionPreset: normalizeImageAspectPreset(imageAspectPreset),
        sessionCustomAspect: imageCustomAspectRatio,
        sessionCustomSize: imageCustomSize,
        hasReference,
      });

  stopBackgroundImageGeneration(sessionId);
  const controller = new AbortController();
  activeJobs.set(sessionId, controller);

  const pendingMsgs: ChatMessage[] =
    replaceIndex !== undefined && fullMessages
      ? fullMessages.map((m, i) =>
          i === replaceIndex ? { role: "assistant", content: IMAGE_PENDING_MARKER } : m,
        )
      : [...localBase, { role: "assistant", content: IMAGE_PENDING_MARKER }];

  let timedOut = false;
  try {
    await syncSessionMessages(sessionId, pendingMsgs, syncOpts);
    notify(sessionId);

    // Longer than the backend read timeout (180s) so a real backend error
    // surfaces first; this timer is only a last-resort client-side stop.
    const timer = window.setTimeout(() => {
      timedOut = true;
      controller.abort();
    }, IMAGE_GENERATION_TIMEOUT_MS);
    let generated: ImagePayload;
    try {
      generated = await requestImageApi(
        resolved.prompt,
        modelId,
        sessionId,
        controller.signal,
        persist,
        referenceImage,
        resolved.useSourceDimensions ? undefined : resolved.aspectRatio,
        resolved.preset,
        undefined,
      );
    } finally {
      window.clearTimeout(timer);
    }

    const imageMsg: ChatMessage = { role: "assistant", content: buildImageMessage(generated), receivedAt: Date.now() };
    if (replaceIndex !== undefined && fullMessages) {
      const next = [...fullMessages];
      next[replaceIndex] = imageMsg;
      await syncSessionMessages(sessionId, next, syncOpts);
    } else {
      const withImage: ChatMessage[] = [...localBase, imageMsg];
      await syncSessionMessages(sessionId, withImage, syncOpts);
    }
    notify(sessionId);
  } catch (err) {
    const aborted = err instanceof DOMException && err.name === "AbortError";
    const errorMsg = aborted
      ? timedOut
        ? IMAGE_TIMEOUT_MESSAGE
        : "Image generation stopped."
      : `Error: ${err instanceof Error ? err.message : String(err)}`;
    if (aborted && !timedOut && persist) {
      await cancelStreamingReplyOnServer(sessionId).catch(() => {});
    } else if (replaceIndex !== undefined && fullMessages) {
      const next = [...fullMessages];
      next[replaceIndex] = { role: "assistant", content: errorMsg, receivedAt: Date.now() };
      await syncSessionMessages(sessionId, stripOrphanImagePending(next), syncOpts);
    } else {
      await syncSessionMessages(
        sessionId,
        buildStoppedImageMessages(localBase, errorMsg),
        syncOpts,
      );
    }
    notify(sessionId);
    if (!aborted) {
      throw err;
    }
  } finally {
    activeJobs.delete(sessionId);
    notify(sessionId);
  }
}

export async function sessionIsPrivate(sessionId: string): Promise<boolean> {
  const session = await fetchSessionWithMessages(sessionId);
  return isPrivateChat(session);
}
