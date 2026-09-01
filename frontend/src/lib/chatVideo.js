/** Background video generation job runner (mirrors chatImage.ts, async poll). */
import { cancelStreamingReplyOnServer, fetchSessionMessagesFromServer, newChatId, syncSessionMessages, } from "./chatStorage";
import { referenceImageFromUserContent, resolveReferenceImageFromUserContent } from "./chatAttachments";
import { authFetch } from "../api";
import { VIDEO_MESSAGE_PREFIX, VIDEO_PENDING_MARKER, } from "./chatMarkers";
export { VIDEO_MESSAGE_PREFIX, VIDEO_PENDING_MARKER } from "./chatMarkers";
export const VIDEO_POLL_INTERVAL_MS = 2500;
export const VIDEO_GENERATION_TIMEOUT_MS = 600_000;
export const VIDEO_TIMEOUT_MESSAGE = "Video generation timed out.";
const activeJobs = new Map();
const listeners = new Set();
function notify(sessionId) {
    listeners.forEach((fn) => {
        try {
            fn(sessionId);
        }
        catch {
            /* ignore */
        }
    });
}
export function subscribeBackgroundVideoUpdates(listener) {
    listeners.add(listener);
    return () => {
        listeners.delete(listener);
    };
}
export function isBackgroundVideoRunning(sessionId) {
    return activeJobs.has(sessionId);
}
export function stopBackgroundVideoGeneration(sessionId) {
    const controller = activeJobs.get(sessionId);
    if (controller) {
        controller.abort();
        activeJobs.delete(sessionId);
        notify(sessionId);
    }
}
export function buildVideoMessage(payload) {
    return `${VIDEO_MESSAGE_PREFIX}${JSON.stringify(payload)}`;
}
export function parseVideoMessage(content) {
    if (!content.startsWith(VIDEO_MESSAGE_PREFIX))
        return null;
    try {
        return JSON.parse(content.slice(VIDEO_MESSAGE_PREFIX.length));
    }
    catch {
        return null;
    }
}
export function lastAssistantImageUrlForVideo(messages) {
    for (let i = messages.length - 1; i >= 0; i -= 1) {
        const msg = messages[i];
        if (msg.role !== "assistant")
            continue;
        if (msg.content === VIDEO_PENDING_MARKER)
            continue;
        // Prefer prior generated image as first frame when available (image prefix).
        if (msg.content.startsWith("__ALPHA_ROUTER_IMAGE_JSON__:")) {
            try {
                const payload = JSON.parse(msg.content.slice("__ALPHA_ROUTER_IMAGE_JSON__:".length));
                if (payload.url?.trim())
                    return payload.url.trim();
            }
            catch {
                /* ignore */
            }
        }
    }
    return undefined;
}
export async function resolveVideoGenerationReferenceAsync(userContent, history, usePriorAssistantImage = false) {
    const fromUser = await resolveReferenceImageFromUserContent(userContent);
    if (fromUser)
        return fromUser;
    if (!usePriorAssistantImage)
        return undefined;
    return lastAssistantImageUrlForVideo(history);
}
export function shouldRouteToVideoGeneration(args) {
    return Boolean(args.videoGenerationEnabled && args.modelSupportsVideo);
}
export function buildVideoRequestBody(args) {
    const operation = args.referenceImage ? "img2vid" : "generation";
    return {
        prompt: args.prompt,
        model: args.model,
        operation,
        reference_image: args.referenceImage || undefined,
        chat_session_id: args.chatSessionId,
        persist: args.persist,
        duration: args.duration ?? 4,
        resolution: args.resolution ?? "720p",
        aspect_ratio: args.aspectRatio ?? "16:9",
        generate_audio: Boolean(args.generateAudio),
        ...(args.assistantClientMessageId
            ? { assistant_client_message_id: args.assistantClientMessageId }
            : {}),
    };
}
async function pollVideoJob(jobId, signal) {
    const started = Date.now();
    while (Date.now() - started < VIDEO_GENERATION_TIMEOUT_MS) {
        if (signal.aborted)
            throw new DOMException("The operation was aborted.", "AbortError");
        const res = await authFetch(`/api/videos/jobs/${jobId}`, { signal });
        if (!res.ok) {
            const text = await res.text();
            throw new Error(text || `Video job status failed (${res.status})`);
        }
        const body = (await res.json());
        const status = (body.status || "").toLowerCase();
        if (status === "completed") {
            // Billing may attach request_log_id a tick after status flips to completed.
            if (typeof body.request_log_id === "number")
                return body;
            await new Promise((resolve) => setTimeout(resolve, 500));
            if (signal.aborted)
                throw new DOMException("The operation was aborted.", "AbortError");
            const retry = await authFetch(`/api/videos/jobs/${jobId}`, { signal });
            if (retry.ok) {
                try {
                    return (await retry.json());
                }
                catch {
                    return body;
                }
            }
            return body;
        }
        if (status === "failed" || status === "cancelled") {
            throw new Error(body.error_message || `Video generation ${status}`);
        }
        await new Promise((resolve) => setTimeout(resolve, VIDEO_POLL_INTERVAL_MS));
    }
    throw new Error(VIDEO_TIMEOUT_MESSAGE);
}
export async function runBackgroundVideoGeneration(args) {
    const { sessionId, prompt, model, userContent, history, persist, duration, resolution, aspectRatio, generateAudio, assistantClientMessageId, onUpdate, getMessages, } = args;
    stopBackgroundVideoGeneration(sessionId);
    const controller = new AbortController();
    activeJobs.set(sessionId, controller);
    notify(sessionId);
    const privateMode = !persist;
    let jobId = null;
    try {
        const referenceImage = await resolveVideoGenerationReferenceAsync(userContent, history, Boolean(referenceImageFromUserContent(userContent)) === false);
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
                const j = JSON.parse(text);
                if (j.detail)
                    detail = j.detail;
            }
            catch {
                /* ignore */
            }
            throw new Error(detail || `Video generation failed (${res.status})`);
        }
        const created = (await res.json());
        jobId = created.id || null;
        if (!jobId)
            throw new Error("Video job id missing from response");
        const finished = await pollVideoJob(jobId, controller.signal);
        const mediaUrl = finished.media_url?.trim();
        if (!mediaUrl)
            throw new Error("Video completed without a media URL");
        const payload = {
            url: mediaUrl,
            prompt: finished.prompt || prompt,
            model: finished.model || model,
            reference_image: referenceImage,
            operation: referenceImage ? "img2vid" : "generation",
            duration: typeof finished.params?.duration === "number" ? finished.params.duration : duration,
            resolution: typeof finished.params?.resolution === "string"
                ? finished.params.resolution
                : resolution,
            aspectRatio: typeof finished.params?.aspect_ratio === "string"
                ? finished.params.aspect_ratio
                : aspectRatio,
        };
        const requestLogId = typeof finished.request_log_id === "number" && Number.isFinite(finished.request_log_id)
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
                if (refreshed.messages.length)
                    onUpdate(refreshed.messages);
            }
            catch {
                /* ignore sync errors after local finalize */
            }
        }
    }
    catch (err) {
        if (controller.signal.aborted) {
            if (jobId) {
                try {
                    await authFetch(`/api/videos/jobs/${jobId}/cancel`, { method: "POST" });
                }
                catch {
                    /* ignore */
                }
            }
            try {
                await cancelStreamingReplyOnServer(sessionId);
            }
            catch {
                /* ignore */
            }
            return;
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
            }
            catch {
                /* keep local error even if sync fails */
            }
        }
        throw err;
    }
    finally {
        if (activeJobs.get(sessionId) === controller) {
            activeJobs.delete(sessionId);
            notify(sessionId);
        }
    }
}
