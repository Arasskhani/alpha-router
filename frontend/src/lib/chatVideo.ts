/** Background video generation job runner (mirrors chatImage.ts, async poll). */

import {
  type ChatMessage,
  cancelStreamingReplyOnServer,
  fetchSessionMessagesFromServer,
  newChatId,
  syncSessionMessages,
} from "./chatStorage";
import { referenceImageFromUserContent, resolveReferenceImageFromUserContent } from "./chatAttachments";
import { lastAssistantImageUrl } from "./chatImage";
import { authFetch } from "../api";
import {
  VIDEO_MESSAGE_PREFIX,
  VIDEO_PENDING_MARKER,
} from "./chatMarkers";

export { VIDEO_MESSAGE_PREFIX, VIDEO_PENDING_MARKER } from "./chatMarkers";

export type VideoPayload = {
  url: string;
  prompt: string;
  model: string;
  reference_image?: string;
  operation?: "generation" | "img2vid";
  duration?: number;
  resolution?: string;
  aspectRatio?: string;
  generateAudio?: boolean;
};

type VideoJobResponse = {
  id?: string;
  status?: string;
  media_url?: string;
  model?: string;
  prompt?: string;
  error_message?: string;
  params?: Record<string, unknown>;
  request_log_id?: number;
};

const VIDEO_POLL_INTERVAL_MS = 2500;
/**
 * Client-side polling budget.
 *
 * This clock must stay comfortably ABOVE every server-side budget, because the
 * server - not the browser - decides whether a job failed. The backend's
 * VIDEO_JOB_TIMEOUT_SECONDS (default 600s) covers only the provider polling
 * loop: it excludes the queue wait before a worker claims the job, and the
 * whole "ingesting" phase (provider download + object-storage write), which
 * has no deadline of its own. VIDEO_JOB_RECLAIM_AFTER_SECONDS (default 900s)
 * is the real upper bound on a live job.
 *
 * A 600s budget here made this poller give up on jobs that then completed
 * normally, leaving "Video generation timed out." in the chat while the video
 * landed in the media library.
 */
const VIDEO_GENERATION_TIMEOUT_MS = 1_200_000;
const VIDEO_TIMEOUT_MESSAGE = "Video generation timed out.";
const VIDEO_STILL_PROCESSING_MESSAGE =
  "This video is taking longer than usual. It is still generating on the server and will appear here, and in your media library, once it finishes.";

/** Raised when the client budget runs out while the server job is still alive. */
class VideoStillProcessingError extends Error {
  readonly jobId: string;
  readonly status: string;

  constructor(jobId: string, status: string) {
    super(VIDEO_STILL_PROCESSING_MESSAGE);
    this.name = "VideoStillProcessingError";
    this.jobId = jobId;
    this.status = status;
  }
}

const activeJobs = new Map<string, AbortController>();
const listeners = new Set<(sessionId: string) => void>();

function notify(sessionId: string) {
  listeners.forEach((fn) => {
    try {
      fn(sessionId);
    } catch {
      /* ignore */
    }
  });
}

export function subscribeBackgroundVideoUpdates(listener: (sessionId: string) => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function isBackgroundVideoRunning(sessionId: string): boolean {
  return activeJobs.has(sessionId);
}

export function stopBackgroundVideoGeneration(sessionId: string) {
  const controller = activeJobs.get(sessionId);
  if (controller) {
    controller.abort();
    activeJobs.delete(sessionId);
    notify(sessionId);
  }
}

export function buildVideoMessage(payload: VideoPayload): string {
  return `${VIDEO_MESSAGE_PREFIX}${JSON.stringify(payload)}`;
}

export function parseVideoMessage(content: string): VideoPayload | null {
  if (!content.startsWith(VIDEO_MESSAGE_PREFIX)) return null;
  try {
    return JSON.parse(content.slice(VIDEO_MESSAGE_PREFIX.length)) as VideoPayload;
  } catch {
    return null;
  }
}

async function resolveVideoGenerationReferenceAsync(
  userContent: string,
  history: ChatMessage[],
  usePriorAssistantImage = false,
): Promise<string | undefined> {
  const fromUser = await resolveReferenceImageFromUserContent(userContent);
  if (fromUser) return fromUser;
  if (!usePriorAssistantImage) return undefined;
  // The prior generated image, as the first frame.
  return lastAssistantImageUrl(history);
}

export function shouldRouteToVideoGeneration(args: {
  videoGenerationEnabled: boolean;
  modelSupportsVideo: boolean;
}): boolean {
  return Boolean(args.videoGenerationEnabled && args.modelSupportsVideo);
}

export function buildVideoRequestBody(args: {
  prompt: string;
  model: string;
  chatSessionId: string | null;
  persist: boolean;
  referenceImage?: string;
  duration?: number;
  resolution?: string;
  aspectRatio?: string;
  generateAudio?: boolean;
  assistantClientMessageId?: string;
}): Record<string, unknown> {
  const operation = args.referenceImage ? "img2vid" : "generation";
  return {
    prompt: args.prompt,
    model: args.model,
    operation,
    reference_image: args.referenceImage || undefined,
    chat_session_id: args.chatSessionId,
    persist: args.persist,
    duration: args.duration,
    resolution: args.resolution ?? "720p",
    aspect_ratio: args.aspectRatio ?? "16:9",
    generate_audio: Boolean(args.generateAudio),
    ...(args.assistantClientMessageId
      ? { assistant_client_message_id: args.assistantClientMessageId }
      : {}),
  };
}

function abortedError(): DOMException {
  return new DOMException("The operation was aborted.", "AbortError");
}

async function fetchVideoJob(jobId: string, signal: AbortSignal): Promise<VideoJobResponse> {
  const res = await authFetch(`/api/videos/jobs/${jobId}`, { signal });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `Video job status failed (${res.status})`);
  }
  return (await res.json()) as VideoJobResponse;
}

async function settleCompletedJob(
  jobId: string,
  body: VideoJobResponse,
  signal: AbortSignal,
): Promise<VideoJobResponse> {
  // Billing may attach request_log_id a tick after status flips to completed.
  if (typeof body.request_log_id === "number") return body;
  await new Promise((resolve) => setTimeout(resolve, 500));
  if (signal.aborted) throw abortedError();
  try {
    return await fetchVideoJob(jobId, signal);
  } catch {
    return body;
  }
}

async function pollVideoJob(
  jobId: string,
  signal: AbortSignal,
): Promise<VideoJobResponse> {
  const started = Date.now();
  let lastStatus = "";
  while (Date.now() - started < VIDEO_GENERATION_TIMEOUT_MS) {
    if (signal.aborted) throw abortedError();
    const body = await fetchVideoJob(jobId, signal);
    const status = (body.status || "").toLowerCase();
    lastStatus = status;
    if (status === "completed") return settleCompletedJob(jobId, body, signal);
    if (status === "failed" || status === "cancelled") {
      throw new Error(body.error_message || `Video generation ${status}`);
    }
    await new Promise((resolve) => setTimeout(resolve, VIDEO_POLL_INTERVAL_MS));
  }

  // Budget spent. Never call it a failure on this clock alone: a job routinely
  // finishes during the ingest phase, after the backend's own deadline. Take
  // one last look and let the server have the final word.
  if (signal.aborted) throw abortedError();
  let finalBody: VideoJobResponse | null = null;
  try {
    finalBody = await fetchVideoJob(jobId, signal);
  } catch (err) {
    if (err instanceof DOMException) throw err;
    finalBody = null;
  }
  // Only an unreachable status endpoint leaves us genuinely in the dark.
  if (!finalBody) throw new Error(VIDEO_TIMEOUT_MESSAGE);
  const finalStatus = (finalBody.status || "").toLowerCase();
  if (finalStatus === "completed") return settleCompletedJob(jobId, finalBody, signal);
  if (finalStatus === "failed" || finalStatus === "cancelled") {
    throw new Error(finalBody.error_message || `Video generation ${finalStatus}`);
  }
  throw new VideoStillProcessingError(jobId, finalStatus || lastStatus);
}

export async function runBackgroundVideoGeneration(args: {
  sessionId: string;
  prompt: string;
  model: string;
  userContent: string;
  history: ChatMessage[];
  persist: boolean;
  duration?: number;
  resolution?: string;
  aspectRatio?: string;
  generateAudio?: boolean;
  assistantClientMessageId?: string;
  onUpdate: (messages: ChatMessage[]) => void;
  getMessages: () => ChatMessage[];
}): Promise<void> {
  const {
    sessionId,
    prompt,
    model,
    userContent,
    history,
    persist,
    duration,
    resolution,
    aspectRatio,
    generateAudio,
    assistantClientMessageId,
    onUpdate,
    getMessages,
  } = args;

  stopBackgroundVideoGeneration(sessionId);
  const controller = new AbortController();
  activeJobs.set(sessionId, controller);
  notify(sessionId);

  const privateMode = !persist;
  let jobId: string | null = null;

  try {
    const referenceImage = await resolveVideoGenerationReferenceAsync(
      userContent,
      history,
      Boolean(referenceImageFromUserContent(userContent)) === false,
    );

    const body = buildVideoRequestBody({
      prompt,
      model,
      chatSessionId: privateMode ? null : sessionId,
      persist: !privateMode,
      referenceImage,
      duration,
      resolution,
      aspectRatio,
      generateAudio,
      assistantClientMessageId,
    });

    const res = await authFetch("/api/videos/generate", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Idempotency-Key": newChatId(),
      },
      body: JSON.stringify(body),
      signal: controller.signal,
    });
    if (!res.ok) {
      const text = await res.text();
      let detail = text;
      try {
        const j = JSON.parse(text) as { detail?: string | { message?: string } };
        // A structured refusal carries a code and a sentence in `detail`.
        if (typeof j.detail === "string") detail = j.detail;
        else if (j.detail?.message) detail = j.detail.message;
      } catch {
        /* ignore */
      }
      throw new Error(detail || `Video generation failed (${res.status})`);
    }
    const created = (await res.json()) as VideoJobResponse;
    jobId = created.id || null;
    if (!jobId) throw new Error("Video job id missing from response");

    const finished = await pollVideoJob(jobId, controller.signal);
    const mediaUrl = finished.media_url?.trim();
    if (!mediaUrl) throw new Error("Video completed without a media URL");

    const payload: VideoPayload = {
      url: mediaUrl,
      prompt: finished.prompt || prompt,
      model: finished.model || model,
      reference_image: referenceImage,
      operation: referenceImage ? "img2vid" : "generation",
      duration: typeof finished.params?.duration === "number" ? finished.params.duration : duration,
      resolution:
        typeof finished.params?.resolution === "string"
          ? finished.params.resolution
          : resolution,
      aspectRatio:
        typeof finished.params?.aspect_ratio === "string"
          ? finished.params.aspect_ratio
          : aspectRatio,
    };

    const requestLogId =
      typeof finished.request_log_id === "number" && Number.isFinite(finished.request_log_id)
        ? finished.request_log_id
        : undefined;
    const messages = getMessages().slice();
    for (let i = messages.length - 1; i >= 0; i -= 1) {
      if (messages[i].role === "assistant" && messages[i].content === VIDEO_PENDING_MARKER) {
        messages[i] = {
          ...messages[i],
          content: buildVideoMessage(payload),
          modelId: payload.model,
          receivedAt: Date.now(),
          streaming: false,
          ...(assistantClientMessageId ? { clientMessageId: assistantClientMessageId } : {}),
          ...(requestLogId != null ? { requestLogId } : {}),
        };
        break;
      }
    }
    onUpdate(messages);
    if (!privateMode) {
      try {
        await syncSessionMessages(sessionId, messages);
        const refreshed = await fetchSessionMessagesFromServer(sessionId);
        if (refreshed.messages.length) onUpdate(refreshed.messages);
      } catch {
        /* ignore sync errors after local finalize */
      }
    }
  } catch (err) {
    if (controller.signal.aborted) {
      if (jobId) {
        try {
          await authFetch(`/api/videos/jobs/${jobId}/cancel`, { method: "POST" });
        } catch {
          /* ignore */
        }
      }
      try {
        await cancelStreamingReplyOnServer(sessionId);
      } catch {
        /* ignore */
      }
      return;
    }
    if (err instanceof VideoStillProcessingError) {
      // Leave the pending marker exactly as it is. The durable worker replaces
      // it with the real video message when ingest finishes, but
      // finalize_chat_session_video only heals a *trailing pending marker* -
      // writing an error over it here would strand the finished video for good.
      throw err;
    }
    const detail = err instanceof Error ? err.message : "Video generation failed";
    const message = detail.startsWith("Error:") ? detail : `Error: ${detail}`;
    const messages = getMessages().slice();
    for (let i = messages.length - 1; i >= 0; i -= 1) {
      if (messages[i].role === "assistant" && messages[i].content === VIDEO_PENDING_MARKER) {
        messages[i] = {
          ...messages[i],
          content: message,
          receivedAt: Date.now(),
          streaming: false,
        };
        break;
      }
    }
    onUpdate(messages);
    if (!privateMode) {
      try {
        await syncSessionMessages(sessionId, messages);
      } catch {
        /* keep local error even if sync fails */
      }
    }
    throw err;
  } finally {
    if (activeJobs.get(sessionId) === controller) {
      activeJobs.delete(sessionId);
      notify(sessionId);
    }
  }
}
