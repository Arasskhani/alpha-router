import { cancelStreamingReplyOnServer, syncSessionMessages, } from "./chatStorage";
import { authFetch } from "../api";
import { SPEECH_MESSAGE_PREFIX, SPEECH_PENDING_MARKER, } from "./chatMarkers";
export { SPEECH_MESSAGE_PREFIX, SPEECH_PENDING_MARKER } from "./chatMarkers";
/** Must exceed the backend speech timeout (120s) so server errors win. */
export const SPEECH_GENERATION_TIMEOUT_MS = 150_000;
export const SPEECH_PREPARATION_TIMEOUT_MS = 15_000;
export const SPEECH_TIMEOUT_MESSAGE = "Speech generation timed out.";
export const SPEECH_PREPARATION_TIMEOUT_MESSAGE = "Preparing the speech request timed out. Please retry.";
const activeJobs = new Map();
const listeners = new Set();
export class SpeechPreparationTimeoutError extends Error {
    constructor() {
        super(SPEECH_PREPARATION_TIMEOUT_MESSAGE);
        this.name = "SpeechPreparationTimeoutError";
    }
}
function speechAbortError() {
    return new DOMException("The operation was aborted.", "AbortError");
}
/** Bound pre-request chat sync and release immediately when the speech job stops. */
export async function awaitSpeechPreparation(work, jobSignal, timeoutMs = SPEECH_PREPARATION_TIMEOUT_MS) {
    if (jobSignal.aborted)
        throw speechAbortError();
    const syncController = new AbortController();
    let timedOut = false;
    const onJobAbort = () => syncController.abort();
    jobSignal.addEventListener("abort", onJobAbort, { once: true });
    let rejectOnAbort;
    const aborted = new Promise((_resolve, reject) => {
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
    }
    finally {
        globalThis.clearTimeout(timer);
        jobSignal.removeEventListener("abort", onJobAbort);
        syncController.signal.removeEventListener("abort", onSyncAbort);
    }
}
function notify(sessionId) {
    listeners.forEach((fn) => {
        try {
            fn(sessionId);
        }
        catch {
            /* ignore listener errors */
        }
    });
}
export function subscribeBackgroundSpeechUpdates(listener) {
    listeners.add(listener);
    return () => {
        listeners.delete(listener);
    };
}
export function isBackgroundSpeechRunning(sessionId) {
    return activeJobs.has(sessionId);
}
export function getBackgroundSpeechSessionIds() {
    return [...activeJobs.keys()];
}
export function stopBackgroundSpeechGeneration(sessionId) {
    const controller = activeJobs.get(sessionId);
    if (controller) {
        controller.abort();
        activeJobs.delete(sessionId);
        notify(sessionId);
    }
}
export function buildSpeechMessage(payload) {
    return `${SPEECH_MESSAGE_PREFIX}${JSON.stringify(payload)}`;
}
export function parseSpeechMessage(content) {
    if (!content.startsWith(SPEECH_MESSAGE_PREFIX))
        return null;
    try {
        return JSON.parse(content.slice(SPEECH_MESSAGE_PREFIX.length));
    }
    catch {
        return null;
    }
}
export function sessionHasPendingSpeech(messages) {
    const last = messages.at(-1);
    return last?.role === "assistant" && last.content === SPEECH_PENDING_MARKER;
}
export function shouldRouteToSpeechGeneration(args) {
    return Boolean(args.speechGenerationEnabled && args.modelSupportsSpeech);
}
/** Drop stale pending placeholders superseded by a later assistant message. */
export function stripOrphanSpeechPending(messages) {
    const last = messages.at(-1);
    if (last?.content === SPEECH_PENDING_MARKER)
        return messages;
    return messages.filter((m) => m.content !== SPEECH_PENDING_MARKER);
}
export function buildStoppedSpeechMessages(messages, stoppedText = "Speech generation stopped.") {
    const withoutPending = stripOrphanSpeechPending(messages.filter((m) => m.content !== SPEECH_PENDING_MARKER));
    const last = withoutPending.at(-1);
    if (last?.role === "assistant" && last.content === stoppedText)
        return withoutPending;
    return [
        ...withoutPending,
        { role: "assistant", content: stoppedText, receivedAt: Date.now() },
    ];
}
function parseApiError(raw, status) {
    try {
        const j = JSON.parse(raw);
        return j.detail || j.message || raw;
    }
    catch {
        return raw || `Request failed (${status})`;
    }
}
export function buildSpeechRequestBody(opts) {
    const body = {
        text: opts.text,
        model: opts.modelId,
        chat_session_id: opts.persist ? opts.sessionId : null,
        persist: opts.persist,
    };
    if (opts.voice)
        body.voice = opts.voice;
    if (opts.format)
        body.response_format = opts.format;
    if (opts.speed !== undefined && Number.isFinite(opts.speed))
        body.speed = opts.speed;
    if (opts.routing)
        body.routing = opts.routing;
    if (opts.assistantClientMessageId) {
        body.assistant_client_message_id = opts.assistantClientMessageId;
    }
    return body;
}
async function requestSpeechApi(text, modelId, sessionId, signal, persist, voice, format, speed, routing, assistantClientMessageId) {
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
    if (!res.ok)
        throw new Error(parseApiError(await res.text(), res.status));
    const result = (await res.json());
    const audioUrl = result.data?.[0]?.url;
    if (!audioUrl)
        throw new Error("Speech model returned no audio URL.");
    const requestLogId = typeof result.request_log_id === "number" && Number.isFinite(result.request_log_id)
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
export async function runBackgroundSpeechGeneration(opts) {
    const { sessionId, localMessages, text, modelId, replaceIndex, fullMessages, privateMode = false, voice, format, speed, routing, assistantClientMessageId, } = opts;
    const persist = !privateMode;
    const syncOpts = { forcePrivate: privateMode };
    const resolvedAssistantId = (assistantClientMessageId || "").trim() ||
        (replaceIndex !== undefined && fullMessages
            ? fullMessages[replaceIndex]?.clientMessageId
            : undefined);
    stopBackgroundSpeechGeneration(sessionId);
    const controller = new AbortController();
    activeJobs.set(sessionId, controller);
    const pendingMsgs = replaceIndex !== undefined && fullMessages
        ? fullMessages.map((m, i) => i === replaceIndex
            ? {
                role: "assistant",
                content: SPEECH_PENDING_MARKER,
                ...(resolvedAssistantId ? { clientMessageId: resolvedAssistantId } : {}),
            }
            : m)
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
    const syncForSpeechJob = (messages, timeoutMs = SPEECH_PREPARATION_TIMEOUT_MS) => awaitSpeechPreparation((signal) => syncSessionMessages(sessionId, messages, { ...syncOpts, signal }), controller.signal, timeoutMs);
    try {
        await syncForSpeechJob(pendingMsgs);
        notify(sessionId);
        const generated = await requestSpeechApi(text, modelId, sessionId, controller.signal, persist, voice, format, speed, routing, resolvedAssistantId);
        const speechMsg = {
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
        }
        else {
            const withSpeech = [...localMessages, speechMsg];
            await syncForSpeechJob(withSpeech);
        }
        notify(sessionId);
    }
    catch (err) {
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
            void cancelStreamingReplyOnServer(sessionId).catch(() => { });
        }
        else if (replaceIndex !== undefined && fullMessages) {
            const next = [...fullMessages];
            next[replaceIndex] = { role: "assistant", content: errorMsg, receivedAt: Date.now() };
            const recoveryController = new AbortController();
            await awaitSpeechPreparation((signal) => syncSessionMessages(sessionId, stripOrphanSpeechPending(next), {
                ...syncOpts,
                signal,
            }), recoveryController.signal, 5_000).catch(() => { });
        }
        else {
            const recoveryController = new AbortController();
            await awaitSpeechPreparation((signal) => syncSessionMessages(sessionId, buildStoppedSpeechMessages(localMessages, errorMsg), {
                ...syncOpts,
                signal,
            }), recoveryController.signal, 5_000).catch(() => { });
        }
        notify(sessionId);
        if (!aborted) {
            throw err;
        }
    }
    finally {
        globalThis.clearTimeout(deadlineTimer);
        if (activeJobs.get(sessionId) === controller) {
            activeJobs.delete(sessionId);
        }
        notify(sessionId);
    }
}
