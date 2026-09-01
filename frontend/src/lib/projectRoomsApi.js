import { api } from "../api";
export const MAX_ROOM_HANDOFF_BRIEF = 8000;
function asNumber(value) {
    if (typeof value === "number" && Number.isFinite(value))
        return value;
    if (typeof value === "string" && value.trim()) {
        const parsed = Number(value);
        return Number.isFinite(parsed) ? parsed : null;
    }
    return null;
}
export function normalizeProjectRoom(raw) {
    return {
        id: String(raw.id || ""),
        title: String(raw.title || "New room"),
        messageCount: Number(raw.messageCount || 0),
        revision: Number(raw.revision || 1),
        channelKind: "member",
        createdByUserId: asNumber(raw.createdByUserId) ?? null,
        createdAt: asNumber(raw.createdAt),
        updatedAt: asNumber(raw.updatedAt),
        lastMessageAt: asNumber(raw.lastMessageAt),
    };
}
export function normalizeProjectRoomMessage(raw) {
    return {
        id: String(raw.id || ""),
        role: "user",
        content: String(raw.content || ""),
        sequence: asNumber(raw.sequence) ?? undefined,
        authorDisplayName: raw.authorDisplayName == null ? null : String(raw.authorDisplayName),
        clientMessageId: raw.clientMessageId == null ? null : String(raw.clientMessageId),
        userId: asNumber(raw.userId),
        mine: Boolean(raw.mine),
        edited: Boolean(raw.edited),
        replyToMessageId: raw.replyToMessageId == null ? null : String(raw.replyToMessageId),
        replyToAuthor: raw.replyToAuthor == null ? null : String(raw.replyToAuthor),
        replyToContent: raw.replyToContent == null ? null : String(raw.replyToContent),
    };
}
export async function listProjectRooms(projectId, opts) {
    const params = new URLSearchParams();
    if (opts?.limit != null)
        params.set("limit", String(opts.limit));
    if (opts?.offset)
        params.set("offset", String(opts.offset));
    if (opts?.q?.trim())
        params.set("q", opts.q.trim());
    const qs = params.toString();
    const data = await api(`/api/projects/${encodeURIComponent(projectId)}/rooms${qs ? `?${qs}` : ""}`);
    return {
        rooms: (data.rooms || []).map((row) => normalizeProjectRoom(row)),
        total: Number(data.total || 0),
    };
}
export async function syncProjectRooms(projectId, opts) {
    const params = new URLSearchParams();
    if (opts?.since != null)
        params.set("since", String(opts.since));
    if (opts?.sessionId)
        params.set("session_id", opts.sessionId);
    if (opts?.afterSequence != null)
        params.set("after_sequence", String(opts.afterSequence));
    const qs = params.toString();
    const data = await api(`/api/projects/${encodeURIComponent(projectId)}/rooms/sync${qs ? `?${qs}` : ""}`);
    return {
        serverTimeMs: Number(data.serverTimeMs || 0),
        aclVersion: asNumber(data.aclVersion) ?? undefined,
        total: Number(data.total || 0),
        sessionIds: Array.isArray(data.sessionIds) ? data.sessionIds.map(String) : [],
        sessions: Array.isArray(data.sessions)
            ? data.sessions.map((row) => normalizeProjectRoom(row))
            : [],
        messages: Array.isArray(data.messages)
            ? data.messages.map((row) => normalizeProjectRoomMessage(row))
            : [],
        messageSessionId: data.messageSessionId == null ? null : String(data.messageSessionId),
        completeWindow: Boolean(data.completeWindow),
        goneSessionId: data.goneSessionId == null ? null : String(data.goneSessionId),
    };
}
export async function createProjectRoom(projectId, body) {
    const data = await api(`/api/projects/${encodeURIComponent(projectId)}/rooms`, { method: "POST", body: JSON.stringify(body ?? {}) });
    return normalizeProjectRoom(data);
}
export async function getProjectRoom(projectId, roomId) {
    const data = await api(`/api/projects/${encodeURIComponent(projectId)}/rooms/${encodeURIComponent(roomId)}`);
    return normalizeProjectRoom(data);
}
export async function deleteProjectRoom(projectId, roomId) {
    return api(`/api/projects/${encodeURIComponent(projectId)}/rooms/${encodeURIComponent(roomId)}`, { method: "DELETE" });
}
export async function listProjectRoomMessages(projectId, roomId, opts) {
    const params = new URLSearchParams();
    if (opts?.limit != null)
        params.set("limit", String(opts.limit));
    if (opts?.before != null)
        params.set("before", String(opts.before));
    const qs = params.toString();
    const data = await api(`/api/projects/${encodeURIComponent(projectId)}/rooms/${encodeURIComponent(roomId)}/messages${qs ? `?${qs}` : ""}`);
    return {
        messages: (data.messages || []).map((row) => normalizeProjectRoomMessage(row)),
        hasMore: Boolean(data.hasMore ?? data.has_more),
    };
}
export async function appendProjectRoomMessage(projectId, roomId, body) {
    const data = await api(`/api/projects/${encodeURIComponent(projectId)}/rooms/${encodeURIComponent(roomId)}/messages`, { method: "POST", body: JSON.stringify(body) });
    return normalizeProjectRoomMessage(data);
}
export async function updateProjectRoomMessage(projectId, roomId, messageId, body) {
    const data = await api(`/api/projects/${encodeURIComponent(projectId)}/rooms/${encodeURIComponent(roomId)}/messages/${encodeURIComponent(messageId)}`, { method: "PATCH", body: JSON.stringify(body) });
    return normalizeProjectRoomMessage(data);
}
export async function deleteProjectRoomMessage(projectId, roomId, messageId) {
    return api(`/api/projects/${encodeURIComponent(projectId)}/rooms/${encodeURIComponent(roomId)}/messages/${encodeURIComponent(messageId)}`, { method: "DELETE" });
}
export async function createProjectRoomHandoff(projectId, roomId, body) {
    const data = await api(`/api/projects/${encodeURIComponent(projectId)}/rooms/${encodeURIComponent(roomId)}/handoffs`, { method: "POST", body: JSON.stringify(body) });
    return {
        targetSessionId: String(data.targetSessionId || ""),
        brief: String(data.brief || ""),
        sourceRoomId: String(data.sourceRoomId || roomId),
    };
}
