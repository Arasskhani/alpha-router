import { cancelStreamingReplyOnServer, fetchSessionWithMessages, isPrivateChat, syncSessionMessages, } from "./chatStorage";
import { referenceImageFromUserContent, resolveReferenceImageFromUserContent } from "./chatAttachments";
import { isPrivateBlobRef, resolvePrivateMediaUrlForApi } from "./privateMediaStore";
import { authFetch } from "../api";
import { normalizeImageAspectPreset, presetFromAspectRatio, resolveImageGeneration, resolveRegenerateImageGeneration, } from "./imageSize";
import { IMAGE_MESSAGE_PREFIX, IMAGE_PENDING_MARKER, SPEECH_MESSAGE_PREFIX, SPEECH_PENDING_MARKER, VIDEO_MESSAGE_PREFIX, VIDEO_PENDING_MARKER, } from "./chatMarkers";
export { IMAGE_MESSAGE_PREFIX, IMAGE_PENDING_MARKER } from "./chatMarkers";
/** Must exceed the backend OpenRouter read timeout (180s) so server errors win. */
export const IMAGE_GENERATION_TIMEOUT_MS = 240_000;
export const IMAGE_PREPARATION_TIMEOUT_MS = 15_000;
export const IMAGE_TIMEOUT_MESSAGE = "Image generation timed out.";
export const IMAGE_PREPARATION_TIMEOUT_MESSAGE = "Preparing the image request timed out. Please retry.";
const activeJobs = new Map();
const listeners = new Set();
export class ImagePreparationTimeoutError extends Error {
    constructor() {
        super(IMAGE_PREPARATION_TIMEOUT_MESSAGE);
        this.name = "ImagePreparationTimeoutError";
    }
}
function imageAbortError() {
    return new DOMException("The operation was aborted.", "AbortError");
}
/** Bound pre-request chat sync and release immediately when the image job stops. */
export async function awaitImagePreparation(work, jobSignal, timeoutMs = IMAGE_PREPARATION_TIMEOUT_MS) {
    if (jobSignal.aborted)
        throw imageAbortError();
    const syncController = new AbortController();
    let timedOut = false;
    const onJobAbort = () => syncController.abort();
    jobSignal.addEventListener("abort", onJobAbort, { once: true });
    let rejectOnAbort;
    const aborted = new Promise((_resolve, reject) => {
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
    }
    finally {
        globalThis.clearTimeout(timer);
        jobSignal.removeEventListener("abort", onJobAbort);
        syncController.signal.removeEventListener("abort", onSyncAbort);
    }
}
function recordImageClientTiming(name, startedAt) {
    try {
        performance.measure(name, { start: startedAt, end: performance.now() });
    }
    catch {
        // Diagnostics must never affect image generation.
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
export function subscribeBackgroundImageUpdates(listener) {
    listeners.add(listener);
    return () => {
        listeners.delete(listener);
    };
}
export function isBackgroundImageRunning(sessionId) {
    return activeJobs.has(sessionId);
}
export function getBackgroundImageSessionIds() {
    return [...activeJobs.keys()];
}
export function stopBackgroundImageGeneration(sessionId) {
    const controller = activeJobs.get(sessionId);
    if (controller) {
        controller.abort();
        activeJobs.delete(sessionId);
        notify(sessionId);
    }
}
export function buildImageMessage(payload) {
    return `${IMAGE_MESSAGE_PREFIX}${JSON.stringify(payload)}`;
}
export function parseImageMessage(content) {
    if (!content.startsWith(IMAGE_MESSAGE_PREFIX))
        return null;
    try {
        return JSON.parse(content.slice(IMAGE_MESSAGE_PREFIX.length));
    }
    catch {
        return null;
    }
}
/** Last generated image in the thread (skips pending placeholders). */
export function lastAssistantImageUrl(messages) {
    for (let i = messages.length - 1; i >= 0; i -= 1) {
        const msg = messages[i];
        if (msg.role !== "assistant")
            continue;
        if (msg.content === IMAGE_PENDING_MARKER)
            continue;
        const payload = parseImageMessage(msg.content);
        const url = payload?.url?.trim();
        if (url)
            return url;
    }
    return undefined;
}
/**
 * Image-to-image reference: explicit attachment, or prior assistant image when editing.
 */
export function resolveImageGenerationReference(userContent, history, usePriorAssistantImage = false) {
    const fromUser = referenceImageFromUserContent(userContent);
    if (fromUser)
        return fromUser;
    if (usePriorAssistantImage)
        return lastAssistantImageUrl(history);
    return undefined;
}
/** Async variant — resolves private blob refs for img2img API calls. */
export async function resolveImageGenerationReferenceAsync(userContent, history, usePriorAssistantImage = false) {
    const fromUser = await resolveReferenceImageFromUserContent(userContent);
    if (fromUser)
        return fromUser;
    if (!usePriorAssistantImage)
        return undefined;
    const fromHistory = lastAssistantImageUrl(history);
    if (!fromHistory)
        return undefined;
    if (isPrivateBlobRef(fromHistory) || fromHistory.startsWith("blob:")) {
        return resolvePrivateMediaUrlForApi(fromHistory);
    }
    return fromHistory;
}
export function sessionHasPendingImage(messages) {
    const last = messages.at(-1);
    return last?.role === "assistant" && last.content === IMAGE_PENDING_MARKER;
}
/** Drop stale pending placeholders superseded by a later assistant message. */
export function stripOrphanImagePending(messages) {
    const last = messages.at(-1);
    if (last?.content === IMAGE_PENDING_MARKER)
        return messages;
    return messages.filter((m) => m.content !== IMAGE_PENDING_MARKER);
}
function lastAssistantContentLen(messages) {
    const last = messages.at(-1);
    if (!last || last.role !== "assistant")
        return 0;
    return (last.content || "").length;
}
/** Prefer the copy with more streamed assistant text when server DB lags behind the client. */
function mergeRequestLogIds(preferred, other) {
    const byClient = new Map();
    for (const msg of [...other, ...preferred]) {
        if (msg.clientMessageId && typeof msg.requestLogId === "number") {
            byClient.set(msg.clientMessageId, msg.requestLogId);
        }
    }
    if (!byClient.size)
        return preferred;
    return preferred.map((msg) => {
        if (typeof msg.requestLogId === "number" || !msg.clientMessageId)
            return msg;
        const requestLogId = byClient.get(msg.clientMessageId);
        return requestLogId != null ? { ...msg, requestLogId } : msg;
    });
}
export function mergeChatMessagesPreferLocal(local, remote, inFlight = false) {
    const cleanedLocal = stripOrphanImagePending(local);
    const cleanedRemote = stripOrphanImagePending(remote);
    if (!cleanedLocal.length)
        return cleanedRemote;
    if (!cleanedRemote.length)
        return cleanedLocal;
    if (inFlight && cleanedLocal.length >= cleanedRemote.length) {
        return mergeRequestLogIds(cleanedLocal, cleanedRemote);
    }
    if (cleanedLocal.length > cleanedRemote.length) {
        return mergeRequestLogIds(cleanedLocal, cleanedRemote);
    }
    const localTailLen = lastAssistantContentLen(cleanedLocal);
    const remoteTailLen = lastAssistantContentLen(cleanedRemote);
    const localLast = cleanedLocal.at(-1);
    const remoteLast = cleanedRemote.at(-1);
    // A locally finalized reply (e.g. "Image generation stopped." after STOP) must
    // not be revived into "generating" by a server copy whose pending marker the
    // cancel request hasn't replaced yet.
    if (localLast?.role === "assistant" &&
        localLast.receivedAt != null &&
        (remoteLast?.content === IMAGE_PENDING_MARKER ||
            remoteLast?.content === VIDEO_PENDING_MARKER ||
            remoteLast?.content === SPEECH_PENDING_MARKER) &&
        cleanedLocal.length >= cleanedRemote.length) {
        return mergeRequestLogIds(cleanedLocal, cleanedRemote);
    }
    if (localLast?.role === "assistant" &&
        remoteLast?.role === "assistant" &&
        localLast.receivedAt == null &&
        localTailLen > remoteTailLen) {
        return mergeRequestLogIds(cleanedLocal, cleanedRemote);
    }
    if (sessionHasIncompleteTextReply(cleanedRemote) &&
        cleanedLocal.length >= cleanedRemote.length &&
        localTailLen >= remoteTailLen) {
        return mergeRequestLogIds(cleanedLocal, cleanedRemote);
    }
    return mergeRequestLogIds(cleanedRemote, cleanedLocal);
}
export function buildStoppedImageMessages(messages, stoppedText = "Image generation stopped.") {
    const withoutPending = stripOrphanImagePending(messages.filter((m) => m.content !== IMAGE_PENDING_MARKER));
    const last = withoutPending.at(-1);
    if (last?.role === "assistant" && last.content === stoppedText)
        return withoutPending;
    return [
        ...withoutPending,
        { role: "assistant", content: stoppedText, receivedAt: Date.now() },
    ];
}
/** True while text stream or media placeholder is still open (server or local). */
export function sessionHasInFlightGeneration(messages) {
    const last = messages.at(-1);
    if (last?.role === "assistant" &&
        (last.content === IMAGE_PENDING_MARKER ||
            last.content === VIDEO_PENDING_MARKER ||
            last.content === SPEECH_PENDING_MARKER)) {
        return true;
    }
    return sessionHasIncompleteTextReply(messages);
}
/** Assistant text reply still being generated on the server (survives page refresh). */
export function sessionHasIncompleteTextReply(messages) {
    const last = messages.at(-1);
    if (!last || last.role !== "assistant")
        return false;
    if (last.content === IMAGE_PENDING_MARKER)
        return false;
    if (last.content === VIDEO_PENDING_MARKER)
        return false;
    if (last.content === SPEECH_PENDING_MARKER)
        return false;
    if (parseImageMessage(last.content))
        return false;
    if (last.content.startsWith(VIDEO_MESSAGE_PREFIX))
        return false;
    if (last.content.startsWith(SPEECH_MESSAGE_PREFIX))
        return false;
    if (last.streaming === true)
        return true;
    return last.receivedAt == null;
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
export function buildImageRequestBody(opts) {
    const operation = opts.referenceImage ? "img2img" : "generation";
    const body = {
        prompt: opts.prompt,
        model: opts.modelId,
        operation,
        reference_image: opts.referenceImage || null,
        chat_session_id: opts.persist ? opts.sessionId : null,
        persist: opts.persist,
    };
    if (opts.imageSizeTier)
        body.image_size_tier = opts.imageSizeTier;
    if (opts.routing)
        body.routing = opts.routing;
    if (opts.assistantClientMessageId) {
        body.assistant_client_message_id = opts.assistantClientMessageId;
    }
    if (opts.referenceImage && opts.sourceSize) {
        body.size = opts.sourceSize;
    }
    else if (opts.aspectRatio) {
        body.aspect_ratio = opts.aspectRatio;
    }
    return body;
}
async function requestImageApi(prompt, modelId, sessionId, signal, persist, referenceImage, aspectRatio, aspectPreset, sourceSize, imageSizeTier, routing, assistantClientMessageId) {
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
        assistantClientMessageId,
    });
    const res = await authFetch("/api/images/generate", {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
        },
        body: JSON.stringify(body),
        signal,
    });
    if (!res.ok)
        throw new Error(parseApiError(await res.text(), res.status));
    const imageResult = (await res.json());
    const first = imageResult?.data?.[0];
    const imageUrl = first?.url || (first?.b64_json ? `data:image/png;base64,${first.b64_json}` : "");
    if (!imageUrl)
        throw new Error("Image model returned no image URL.");
    const appliedAspect = imageResult.aspect_ratio || aspectRatio;
    const appliedPreset = presetFromAspectRatio(appliedAspect) ?? aspectPreset;
    const requestLogId = typeof imageResult.request_log_id === "number" && Number.isFinite(imageResult.request_log_id)
        ? imageResult.request_log_id
        : undefined;
    return {
        url: imageUrl,
        prompt,
        model: imageResult.model || modelId,
        aspectRatio: appliedAspect || undefined,
        aspectPreset: appliedPreset,
        size: imageResult.size || sourceSize,
        ...(imageResult.image_size_tier ? { imageSizeTier: imageResult.image_size_tier } : {}),
        ...(imageResult.routing ? { routing: imageResult.routing } : {}),
        ...(referenceImage ? { reference_image: referenceImage, operation: "img2img" } : { operation: "generation" }),
        ...(requestLogId != null ? { requestLogId } : {}),
    };
}
/** Runs image generation outside React lifecycle; survives route changes within the SPA. */
export async function runBackgroundImageGeneration(opts) {
    const { sessionId, historyWithUser, localMessageBase, prompt, modelId, replaceIndex, fullMessages, privateMode = false, referenceImage, imageAspectPreset, imageCustomAspectRatio, imageCustomSize, regenerateFrom, assistantClientMessageId, } = opts;
    const persist = !privateMode;
    const hasReference = Boolean(referenceImage?.trim());
    const localBase = localMessageBase ?? historyWithUser;
    const syncOpts = { forcePrivate: privateMode };
    const resolvedAssistantId = (assistantClientMessageId || "").trim() ||
        (replaceIndex !== undefined && fullMessages
            ? fullMessages[replaceIndex]?.clientMessageId
            : undefined);
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
    const pendingMsgs = replaceIndex !== undefined && fullMessages
        ? fullMessages.map((m, i) => i === replaceIndex
            ? {
                role: "assistant",
                content: IMAGE_PENDING_MARKER,
                ...(resolvedAssistantId ? { clientMessageId: resolvedAssistantId } : {}),
            }
            : m)
        : [
            ...localBase,
            {
                role: "assistant",
                content: IMAGE_PENDING_MARKER,
                ...(resolvedAssistantId ? { clientMessageId: resolvedAssistantId } : {}),
            },
        ];
    let timedOut = false;
    const deadlineTimer = globalThis.setTimeout(() => {
        timedOut = true;
        controller.abort();
    }, IMAGE_GENERATION_TIMEOUT_MS);
    const syncForImageJob = (messages, timeoutMs = IMAGE_PREPARATION_TIMEOUT_MS) => awaitImagePreparation((signal) => syncSessionMessages(sessionId, messages, { ...syncOpts, signal }), controller.signal, timeoutMs);
    try {
        const preparationStartedAt = performance.now();
        await syncForImageJob(pendingMsgs);
        recordImageClientTiming("alpha-router:image:preparation", preparationStartedAt);
        notify(sessionId);
        const generated = await requestImageApi(resolved.prompt, modelId, sessionId, controller.signal, persist, referenceImage, resolved.useSourceDimensions ? undefined : resolved.aspectRatio, resolved.preset, undefined, opts.imageSizeTier, opts.routing, resolvedAssistantId);
        const imageMsg = {
            role: "assistant",
            content: buildImageMessage(generated),
            receivedAt: Date.now(),
            ...(resolvedAssistantId ? { clientMessageId: resolvedAssistantId } : {}),
            ...(generated.requestLogId != null ? { requestLogId: generated.requestLogId } : {}),
        };
        if (replaceIndex !== undefined && fullMessages) {
            const next = [...fullMessages];
            next[replaceIndex] = imageMsg;
            await syncForImageJob(next);
        }
        else {
            const withImage = [...localBase, imageMsg];
            await syncForImageJob(withImage);
        }
        recordImageClientTiming("alpha-router:image:total", operationStartedAt);
        notify(sessionId);
    }
    catch (err) {
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
            void cancelStreamingReplyOnServer(sessionId).catch(() => { });
        }
        else if (replaceIndex !== undefined && fullMessages) {
            const next = [...fullMessages];
            next[replaceIndex] = { role: "assistant", content: errorMsg, receivedAt: Date.now() };
            const recoveryController = new AbortController();
            await awaitImagePreparation((signal) => syncSessionMessages(sessionId, stripOrphanImagePending(next), {
                ...syncOpts,
                signal,
            }), recoveryController.signal, 5_000).catch(() => { });
        }
        else {
            const recoveryController = new AbortController();
            await awaitImagePreparation((signal) => syncSessionMessages(sessionId, buildStoppedImageMessages(localBase, errorMsg), {
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
export async function sessionIsPrivate(sessionId) {
    const session = await fetchSessionWithMessages(sessionId);
    return isPrivateChat(session);
}
