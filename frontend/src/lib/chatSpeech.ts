import {
  type ChatMessage,
  cancelStreamingReplyOnServer,
  syncSessionMessages,
} from "./chatStorage";
import { authFetch } from "../api";
import { humanizeGatewayError } from "./gatewayErrors";
import {
  SPEECH_MESSAGE_PREFIX,
  SPEECH_PENDING_MARKER,
} from "./chatMarkers";

export { SPEECH_MESSAGE_PREFIX, SPEECH_PENDING_MARKER } from "./chatMarkers";

export type SpeechPayload = {
  url: string;
  prompt: string;
  model: string;
  voice?: string;
  format?: string;
  duration_seconds?: number;
  characters?: number;
};

type SpeechResponse = {
  data?: Array<{ url?: string }>;
  format?: string;
  voice?: string;
  model?: string;
  characters?: number;
  duration_seconds?: number;
  request_log_id?: number;
};

/** Must exceed the backend speech timeout (120s) so server errors win. */
export const SPEECH_GENERATION_TIMEOUT_MS = 150_000;
export const SPEECH_PREPARATION_TIMEOUT_MS = 15_000;
export const SPEECH_TIMEOUT_MESSAGE = "Speech generation timed out.";
export const SPEECH_PREPARATION_TIMEOUT_MESSAGE =
  "Preparing the speech request timed out. Please retry.";

const activeJobs = new Map<string, AbortController>();
const listeners = new Set<(sessionId: string) => void>();

export class SpeechPreparationTimeoutError extends Error {
  constructor() {
    super(SPEECH_PREPARATION_TIMEOUT_MESSAGE);
    this.name = "SpeechPreparationTimeoutError";
  }
}

function speechAbortError(): DOMException {
  return new DOMException("The operation was aborted.", "AbortError");
}

/** Bound pre-request chat sync and release immediately when the speech job stops. */
export async function awaitSpeechPreparation<T>(
  work: (signal: AbortSignal) => Promise<T>,
  jobSignal: AbortSignal,
  timeoutMs = SPEECH_PREPARATION_TIMEOUT_MS,
): Promise<T> {
  if (jobSignal.aborted) throw speechAbortError();

  const syncController = new AbortController();
  let timedOut = false;
  const onJobAbort = () => syncController.abort();
  jobSignal.addEventListener("abort", onJobAbort, { once: true });

  let rejectOnAbort: ((reason?: unknown) => void) | undefined;
  const aborted = new Promise<never>((_resolve, reject) => {
    rejectOnAbort = reject;
  });
  const onSyncAbort = () => {
    rejectOnAbort?.(timedOut ? new SpeechPreparationTimeoutError() : speechAbortError());
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

function notify(sessionId: string) {
  listeners.forEach((fn) => {
    try {
      fn(sessionId);
    } catch {
      /* ignore listener errors */
    }
  });
}

export function subscribeBackgroundSpeechUpdates(listener: (sessionId: string) => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function isBackgroundSpeechRunning(sessionId: string): boolean {
  return activeJobs.has(sessionId);
}

export function getBackgroundSpeechSessionIds(): string[] {
  return [...activeJobs.keys()];
}

export function stopBackgroundSpeechGeneration(sessionId: string) {
  const controller = activeJobs.get(sessionId);
  if (controller) {
    controller.abort();
    activeJobs.delete(sessionId);
    notify(sessionId);
  }
}

export function buildSpeechMessage(payload: SpeechPayload): string {
  return `${SPEECH_MESSAGE_PREFIX}${JSON.stringify(payload)}`;
}

export function parseSpeechMessage(content: string): SpeechPayload | null {
  if (!content.startsWith(SPEECH_MESSAGE_PREFIX)) return null;
  try {
    return JSON.parse(content.slice(SPEECH_MESSAGE_PREFIX.length)) as SpeechPayload;
  } catch {
    return null;
  }
}

export function sessionHasPendingSpeech(messages: ChatMessage[]): boolean {
  const last = messages.at(-1);
  return last?.role === "assistant" && last.content === SPEECH_PENDING_MARKER;
}

export function shouldRouteToSpeechGeneration(args: {
  speechGenerationEnabled: boolean;
  modelSupportsSpeech: boolean;
}): boolean {
  return Boolean(args.speechGenerationEnabled && args.modelSupportsSpeech);
}

/** Drop stale pending placeholders superseded by a later assistant message. */
export function stripOrphanSpeechPending(messages: ChatMessage[]): ChatMessage[] {
  const last = messages.at(-1);
  if (last?.content === SPEECH_PENDING_MARKER) return messages;
  return messages.filter((m) => m.content !== SPEECH_PENDING_MARKER);
}

export function buildStoppedSpeechMessages(
  messages: ChatMessage[],
  stoppedText = "Speech generation stopped.",
): ChatMessage[] {
  const withoutPending = stripOrphanSpeechPending(
    messages.filter((m) => m.content !== SPEECH_PENDING_MARKER),
  );
  const last = withoutPending.at(-1);
  if (last?.role === "assistant" && last.content === stoppedText) return withoutPending;
  return [
    ...withoutPending,
    { role: "assistant", content: stoppedText, receivedAt: Date.now() },
  ];
}

function parseApiError(raw: string, status: number): string {
  try {
    const j = JSON.parse(raw);
    return j.detail || j.message || raw;
  } catch {
    return humanizeGatewayError(raw, status);
  }
}

export function buildSpeechRequestBody(opts: {
  text: string;
  modelId: string;
  sessionId: string;
  persist: boolean;
  voice?: string;
  format?: string;
  speed?: number;
  routing?: Record<string, unknown>;
  assistantClientMessageId?: string;
}): Record<string, unknown> {
  const body: Record<string, unknown> = {
    text: opts.text,
    model: opts.modelId,
    chat_session_id: opts.persist ? opts.sessionId : null,
    persist: opts.persist,
  };
  if (opts.voice) body.voice = opts.voice;
  if (opts.format) body.response_format = opts.format;
  if (opts.speed !== undefined && Number.isFinite(opts.speed)) body.speed = opts.speed;
  if (opts.routing) body.routing = opts.routing;
  if (opts.assistantClientMessageId) {
    body.assistant_client_message_id = opts.assistantClientMessageId;
  }
  return body;
}

type SpeechApiResult = SpeechPayload & { requestLogId?: number };

async function requestSpeechApi(
  text: string,
  modelId: string,
  sessionId: string,
  signal: AbortSignal,
  persist: boolean,
  voice: string | undefined,
  format: string | undefined,
  speed: number | undefined,
  routing: Record<string, unknown> | undefined,
  assistantClientMessageId?: string,
): Promise<SpeechApiResult> {
  const body = buildSpeechRequestBody({
    text,
    modelId,
    sessionId,
    persist,
    voice,
    format,
    speed,
    routing,
    assistantClientMessageId,
  });
  const res = await authFetch("/api/speech/generate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  if (!res.ok) throw new Error(parseApiError(await res.text(), res.status));
  const result = (await res.json()) as SpeechResponse;
  const audioUrl = result.data?.[0]?.url;
  if (!audioUrl) throw new Error("Speech model returned no audio URL.");
  const requestLogId =
    typeof result.request_log_id === "number" && Number.isFinite(result.request_log_id)
      ? result.request_log_id
      : undefined;
  return {
    url: audioUrl,
    prompt: text,
    model: result.model || modelId,
    voice: result.voice || voice,
    format: result.format || format,
    characters: result.characters,
    duration_seconds: result.duration_seconds,
    ...(requestLogId != null ? { requestLogId } : {}),
  };
}

/** Runs speech generation outside React lifecycle; survives route changes within the SPA. */
export async function runBackgroundSpeechGeneration(opts: {
  sessionId: string;
  /** Full local thread for UI sync. */
  localMessages: ChatMessage[];
  text: string;
  modelId: string;
  privateMode?: boolean;
  voice?: string;
  format?: string;
  speed?: number;
  routing?: Record<string, unknown>;
  /** When set, pending/final speech replace this index instead of appending. */
  replaceIndex?: number;
  fullMessages?: ChatMessage[];
  assistantClientMessageId?: string;
}): Promise<void> {
  const {
    sessionId,
    localMessages,
    text,
    modelId,
    replaceIndex,
    fullMessages,
    privateMode = false,
    voice,
    format,
    speed,
    routing,
    assistantClientMessageId,
  } = opts;
  const persist = !privateMode;
  const syncOpts = { forcePrivate: privateMode };
  const resolvedAssistantId =
    (assistantClientMessageId || "").trim() ||
    (replaceIndex !== undefined && fullMessages
      ? fullMessages[replaceIndex]?.clientMessageId
      : undefined);

  stopBackgroundSpeechGeneration(sessionId);
  const controller = new AbortController();
  activeJobs.set(sessionId, controller);

  const pendingMsgs: ChatMessage[] =
    replaceIndex !== undefined && fullMessages
      ? fullMessages.map((m, i) =>
          i === replaceIndex
            ? {
                role: "assistant",
                content: SPEECH_PENDING_MARKER,
                ...(resolvedAssistantId ? { clientMessageId: resolvedAssistantId } : {}),
              }
            : m,
        )
      : [
          ...localMessages,
          {
            role: "assistant",
            content: SPEECH_PENDING_MARKER,
            ...(resolvedAssistantId ? { clientMessageId: resolvedAssistantId } : {}),
          },
        ];

  let timedOut = false;
  const deadlineTimer = globalThis.setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, SPEECH_GENERATION_TIMEOUT_MS);
  const syncForSpeechJob = (messages: ChatMessage[], timeoutMs = SPEECH_PREPARATION_TIMEOUT_MS) =>
    awaitSpeechPreparation(
      (signal) => syncSessionMessages(sessionId, messages, { ...syncOpts, signal }),
      controller.signal,
      timeoutMs,
    );

  try {
    await syncForSpeechJob(pendingMsgs);
    notify(sessionId);

    const generated = await requestSpeechApi(
      text,
      modelId,
      sessionId,
      controller.signal,
      persist,
      voice,
      format,
      speed,
      routing,
      resolvedAssistantId,
    );

    const speechMsg: ChatMessage = {
      role: "assistant",
      content: buildSpeechMessage(generated),
      receivedAt: Date.now(),
      ...(resolvedAssistantId ? { clientMessageId: resolvedAssistantId } : {}),
      ...(generated.requestLogId != null ? { requestLogId: generated.requestLogId } : {}),
    };
    if (replaceIndex !== undefined && fullMessages) {
      const next = [...fullMessages];
      next[replaceIndex] = speechMsg;
      await syncForSpeechJob(next);
    } else {
      const withSpeech: ChatMessage[] = [...localMessages, speechMsg];
      await syncForSpeechJob(withSpeech);
    }
    notify(sessionId);
  } catch (err) {
    const aborted = err instanceof DOMException && err.name === "AbortError";
    const preparationTimedOut = err instanceof SpeechPreparationTimeoutError;
    const errorMsg = preparationTimedOut
      ? SPEECH_PREPARATION_TIMEOUT_MESSAGE
      : aborted
      ? timedOut
        ? SPEECH_TIMEOUT_MESSAGE
        : "Speech generation stopped."
      : `Error: ${err instanceof Error ? err.message : String(err)}`;
    if (aborted && !timedOut && persist) {
      void cancelStreamingReplyOnServer(sessionId).catch(() => {});
    } else if (replaceIndex !== undefined && fullMessages) {
      const next = [...fullMessages];
      next[replaceIndex] = { role: "assistant", content: errorMsg, receivedAt: Date.now() };
      const recoveryController = new AbortController();
      await awaitSpeechPreparation(
        (signal) =>
          syncSessionMessages(sessionId, stripOrphanSpeechPending(next), {
            ...syncOpts,
            signal,
          }),
        recoveryController.signal,
        5_000,
      ).catch(() => {});
    } else {
      const recoveryController = new AbortController();
      await awaitSpeechPreparation(
        (signal) =>
          syncSessionMessages(sessionId, buildStoppedSpeechMessages(localMessages, errorMsg), {
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
