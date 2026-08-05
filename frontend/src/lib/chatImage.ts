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
import { authFetch } from "../api";
import {
  normalizeImageAspectPreset,
  presetFromAspectRatio,
  resolveImageGeneration,
  resolveRegenerateImageGeneration,
  type ImageAspectPresetId,
} from "./imageSize";
import {
  IMAGE_MESSAGE_PREFIX,
  IMAGE_PENDING_MARKER,
} from "./chatMarkers";

export { IMAGE_MESSAGE_PREFIX, IMAGE_PENDING_MARKER } from "./chatMarkers";

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
  /** OpenRouter image generation tier used by the successful request. */
  imageSizeTier?: string;
  routing?: Record<string, unknown>;
};

type ImageResponse = {
  data?: Array<{ url?: string; b64_json?: string }>;
  size?: string;
  aspect_ratio?: string;
  model?: string;
  routing?: Record<string, unknown>;
  image_size_tier?: string;
};

/** Must exceed the backend OpenRouter read timeout (180s) so server errors win. */
export const IMAGE_GENERATION_TIMEOUT_MS = 240_000;
export const IMAGE_PREPARATION_TIMEOUT_MS = 15_000;
export const IMAGE_TIMEOUT_MESSAGE = "Image generation timed out.";
export const IMAGE_PREPARATION_TIMEOUT_MESSAGE =
  "Preparing the image request timed out. Please retry.";

const activeJobs = new Map<string, AbortController>();
const listeners = new Set<(sessionId: string) => void>();

export class ImagePreparationTimeoutError extends Error {
  constructor() {
    super(IMAGE_PREPARATION_TIMEOUT_MESSAGE);
    this.name = "ImagePreparationTimeoutError";
  }
}

function imageAbortError(): DOMException {
  return new DOMException("The operation was aborted.", "AbortError");
}

/** Bound pre-request chat sync and release immediately when the image job stops. */
export async function awaitImagePreparation<T>(
  work: (signal: AbortSignal) => Promise<T>,
  jobSignal: AbortSignal,
  timeoutMs = IMAGE_PREPARATION_TIMEOUT_MS,
): Promise<T> {
  if (jobSignal.aborted) throw imageAbortError();

  const syncController = new AbortController();
  let timedOut = false;
  const onJobAbort = () => syncController.abort();
  jobSignal.addEventListener("abort", onJobAbort, { once: true });

  let rejectOnAbort: ((reason?: unknown) => void) | undefined;
  const aborted = new Promise<never>((_resolve, reject) => {
    rejectOnAbort = reject;
  });
  const onSyncAbort = () => {
    rejectOnAbort?.(timedOut ? new ImagePreparationTimeoutError() : imageAbortError());
  };
  syncController.signal.addEventListener("abort", onSyncAbort, { once: true });

  const timer = globalThis.setTimeout(() => {
    timedOut = true;
    syncController.abort();
  }, Math.max(1, timeoutMs));

  try {
    return await Promise.race([work(syncController.signal), aborted]);
  } finally {
    globalThis.clearTimeout(timer);
    jobSignal.removeEventListener("abort", onJobAbort);
    syncController.signal.removeEventListener("abort", onSyncAbort);
  }
}

function recordImageClientTiming(name: string, startedAt: number): void {
  try {
    performance.measure(name, { start: startedAt, end: performance.now() });
  } catch {
    // Diagnostics must never affect image generation.
  }
}

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
    notify(sessionId);
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

export function buildImageRequestBody(opts: {
  prompt: string;
  modelId: string;
  sessionId: string;
  persist: boolean;
  referenceImage?: string;
  aspectRatio?: string;
  sourceSize?: string;
  imageSizeTier?: string;
  routing?: Record<string, unknown>;
}): Record<string, unknown> {
  const operation = opts.referenceImage ? "img2img" : "generation";
  const body: Record<string, unknown> = {
    prompt: opts.prompt,
    model: opts.modelId,
    operation,
    reference_image: opts.referenceImage || null,
    chat_session_id: opts.persist ? opts.sessionId : null,
    persist: opts.persist,
  };
  if (opts.imageSizeTier) body.image_size_tier = opts.imageSizeTier;
  if (opts.routing) body.routing = opts.routing;
  if (opts.referenceImage && opts.sourceSize) {
    body.size = opts.sourceSize;
  } else if (opts.aspectRatio) {
    body.aspect_ratio = opts.aspectRatio;
  }
  return body;
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
  imageSizeTier: string | undefined,
  routing: Record<string, unknown> | undefined,
): Promise<ImagePayload> {
  const resolvedReference = referenceImage
    ? await resolvePrivateMediaUrlForApi(referenceImage)
    : undefined;
  const body = buildImageRequestBody({
    prompt,
    modelId,
    sessionId,
    persist,
    referenceImage: resolvedReference,
    aspectRatio,
    sourceSize,
    imageSizeTier,
    routing,
  });
  const res = await authFetch("/api/images/generate", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
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
    model: imageResult.model || modelId,
    aspectRatio: appliedAspect || undefined,
    aspectPreset: appliedPreset,
    size: imageResult.size || sourceSize,
    ...(imageResult.image_size_tier ? { imageSizeTier: imageResult.image_size_tier } : {}),
    ...(imageResult.routing ? { routing: imageResult.routing } : {}),
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
  /** Reuse provider routing details from a successful image request. */
  imageSizeTier?: string;
  routing?: Record<string, unknown>;
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
  const operationStartedAt = performance.now();

  const pendingMsgs: ChatMessage[] =
    replaceIndex !== undefined && fullMessages
      ? fullMessages.map((m, i) =>
          i === replaceIndex ? { role: "assistant", content: IMAGE_PENDING_MARKER } : m,
        )
      : [...localBase, { role: "assistant", content: IMAGE_PENDING_MARKER }];

  let timedOut = false;
  const deadlineTimer = globalThis.setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, IMAGE_GENERATION_TIMEOUT_MS);
  const syncForImageJob = (messages: ChatMessage[], timeoutMs = IMAGE_PREPARATION_TIMEOUT_MS) =>
    awaitImagePreparation(
      (signal) => syncSessionMessages(sessionId, messages, { ...syncOpts, signal }),
      controller.signal,
      timeoutMs,
    );

  try {
    const preparationStartedAt = performance.now();
    await syncForImageJob(pendingMsgs);
    recordImageClientTiming("alpha-router:image:preparation", preparationStartedAt);
    notify(sessionId);

    let generated: ImagePayload;
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
      opts.imageSizeTier,
      opts.routing,
    );

    const imageMsg: ChatMessage = { role: "assistant", content: buildImageMessage(generated), receivedAt: Date.now() };
    if (replaceIndex !== undefined && fullMessages) {
      const next = [...fullMessages];
      next[replaceIndex] = imageMsg;
      await syncForImageJob(next);
    } else {
      const withImage: ChatMessage[] = [...localBase, imageMsg];
      await syncForImageJob(withImage);
    }
    recordImageClientTiming("alpha-router:image:total", operationStartedAt);
    notify(sessionId);
  } catch (err) {
    const aborted = err instanceof DOMException && err.name === "AbortError";
    const preparationTimedOut = err instanceof ImagePreparationTimeoutError;
    const errorMsg = preparationTimedOut
      ? IMAGE_PREPARATION_TIMEOUT_MESSAGE
      : aborted
      ? timedOut
        ? IMAGE_TIMEOUT_MESSAGE
        : "Image generation stopped."
      : `Error: ${err instanceof Error ? err.message : String(err)}`;
    if (aborted && !timedOut && persist) {
      void cancelStreamingReplyOnServer(sessionId).catch(() => {});
    } else if (replaceIndex !== undefined && fullMessages) {
      const next = [...fullMessages];
      next[replaceIndex] = { role: "assistant", content: errorMsg, receivedAt: Date.now() };
      const recoveryController = new AbortController();
      await awaitImagePreparation(
        (signal) =>
          syncSessionMessages(sessionId, stripOrphanImagePending(next), {
            ...syncOpts,
            signal,
          }),
        recoveryController.signal,
        5_000,
      ).catch(() => {});
    } else {
      const recoveryController = new AbortController();
      await awaitImagePreparation(
        (signal) =>
          syncSessionMessages(sessionId, buildStoppedImageMessages(localBase, errorMsg), {
            ...syncOpts,
            signal,
          }),
        recoveryController.signal,
        5_000,
      ).catch(() => {});
    }
    notify(sessionId);
    if (!aborted) {
      throw err;
    }
  } finally {
    globalThis.clearTimeout(deadlineTimer);
    if (activeJobs.get(sessionId) === controller) {
      activeJobs.delete(sessionId);
    }
    notify(sessionId);
  }
}

export async function sessionIsPrivate(sessionId: string): Promise<boolean> {
  const session = await fetchSessionWithMessages(sessionId);
  return isPrivateChat(session);
}
