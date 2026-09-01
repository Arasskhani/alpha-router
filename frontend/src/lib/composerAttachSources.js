import { api } from "../api";
import { attachmentKindFromName, canProcessAttachmentLocally, } from "./chatAttachments";
import { fetchAuthenticatedMediaBlob } from "./mediaUrl";
import { listProjectMedia } from "./projectsApi";
export function normalizeUserMediaItem(item) {
    return {
        id: item.id,
        kind: item.kind,
        fileName: item.file_name,
        mimeType: item.mime_type,
        url: item.url,
        sizeBytes: item.size_bytes,
        createdAt: item.created_at,
    };
}
export function normalizeProjectMediaItem(item) {
    return {
        id: item.id,
        kind: item.kind,
        fileName: item.fileName,
        mimeType: item.mimeType,
        url: item.url,
        sizeBytes: item.sizeBytes,
        createdAt: item.createdAt,
    };
}
export function composerAttachEligibility(item, opts) {
    const mime = (item.mimeType || "").toLowerCase();
    const kind = (item.kind || "").toLowerCase();
    if (kind === "video" || mime.startsWith("video/")) {
        return { attachable: false, reason: "Video files cannot be attached to chat." };
    }
    const processedKind = attachmentKindFromName(item.fileName);
    if (!processedKind) {
        return { attachable: false, reason: "This file type cannot be attached to chat." };
    }
    if (opts.privateMode && !canProcessAttachmentLocally(item.fileName)) {
        return {
            attachable: false,
            reason: "Private Mode can only attach images or plain-text files from Media.",
        };
    }
    return { attachable: true, reason: null, processedKind };
}
export function capAttachSelection(currentIds, togglingId, remainingSlots) {
    if (currentIds.includes(togglingId)) {
        return { ids: currentIds.filter((id) => id !== togglingId), blocked: false };
    }
    if (remainingSlots <= 0 || currentIds.length >= remainingSlots) {
        return { ids: currentIds, blocked: true };
    }
    return { ids: [...currentIds, togglingId], blocked: false };
}
export function attachSlotOverflowMessage(remainingSlots) {
    if (remainingSlots <= 0) {
        return "You can attach no more files. Remove one first.";
    }
    return remainingSlots === 1
        ? "You can attach 1 more file."
        : `You can attach up to ${remainingSlots} more files.`;
}
export function mediaBlobToFile(blob, item) {
    let name = item.fileName || "attachment";
    if (!name.includes(".")) {
        const ext = (item.mimeType || blob.type || "").split("/")[1]?.split("+")[0];
        if (ext)
            name = `${name}.${ext}`;
    }
    return new File([blob], name, {
        type: item.mimeType || blob.type || "application/octet-stream",
    });
}
export async function mediaCandidatesToFiles(items) {
    const files = [];
    for (const item of items) {
        const blob = await fetchAuthenticatedMediaBlob(item.url);
        files.push(mediaBlobToFile(blob, item));
    }
    return files;
}
export async function attachMediaIds(opts) {
    const mediaIds = [...new Set(opts.mediaIds.filter((id) => Number.isInteger(id) && id > 0))];
    if (!mediaIds.length)
        return [];
    const body = { media_ids: mediaIds };
    if (opts.chatSessionId)
        body.chat_session_id = opts.chatSessionId;
    if (opts.projectId)
        body.project_id = opts.projectId;
    const data = await api("/api/chat/attachments/from-media", { method: "POST", body: JSON.stringify(body) });
    return data.attachments || [];
}
export async function listComposerAttachMedia(opts) {
    const limit = opts.limit ?? 200;
    const q = opts.query?.trim() || undefined;
    if (opts.projectId) {
        const res = await listProjectMedia(opts.projectId, { q, limit });
        return {
            items: res.items.map(normalizeProjectMediaItem),
            total: res.total,
        };
    }
    const params = new URLSearchParams();
    params.set("limit", String(limit));
    if (q)
        params.set("q", q);
    const res = await api(`/api/user/media?${params}`);
    return {
        items: res.items.map(normalizeUserMediaItem),
        total: res.total,
    };
}
