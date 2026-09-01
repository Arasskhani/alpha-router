import { mergeRemoteChatSessions } from "./chatStorage";
export function sortProjectSessions(sessions) {
    return [...sessions].sort((a, b) => {
        const pin = Number(!!b.pinned) - Number(!!a.pinned);
        if (pin)
            return pin;
        return (b.lastMessageAt ?? b.updatedAt) - (a.lastMessageAt ?? a.updatedAt);
    });
}
export function applyProjectPins(sessions, pinnedSessionIds) {
    const pinned = new Set(pinnedSessionIds);
    return sessions.map((session) => session.pinned === pinned.has(session.id)
        ? session
        : { ...session, pinned: pinned.has(session.id) });
}
function messageKey(message) {
    if (message.clientMessageId)
        return `c:${message.clientMessageId}`;
    if (message.id)
        return `i:${message.id}`;
    if (typeof message.sequence === "number")
        return `s:${message.sequence}`;
    return null;
}
function projectMessageNeedsUpdate(local, incoming) {
    return (local.content !== incoming.content ||
        local.id !== incoming.id ||
        local.sequence !== incoming.sequence ||
        local.authorDisplayName !== incoming.authorDisplayName ||
        local.receivedAt !== incoming.receivedAt ||
        local.streaming !== incoming.streaming ||
        local.modelId !== incoming.modelId ||
        local.modelName !== incoming.modelName);
}
/** Merge a live project-sync row onto a local message without clobbering richer local state. */
export function mergeProjectMessage(local, incoming) {
    const merged = { ...local, ...incoming };
    if (!(incoming.content || "").trim() && (local.content || "").trim()) {
        merged.content = local.content;
    }
    if (incoming.receivedAt == null && local.receivedAt != null) {
        merged.receivedAt = local.receivedAt;
    }
    if (incoming.streaming == null && local.streaming != null) {
        merged.streaming = local.streaming;
    }
    if (!incoming.modelId && local.modelId)
        merged.modelId = local.modelId;
    if (!incoming.modelName && local.modelName)
        merged.modelName = local.modelName;
    return merged;
}
/**
 * Prefer the on-screen thread when the sidebar row is empty or shorter.
 * A longer sidebar copy wins so a previous incremental merge is not discarded.
 */
export function pickProjectSyncMessageBase(sessionMessages, displayedMessages) {
    if (!displayedMessages?.length)
        return sessionMessages;
    if (!sessionMessages.length)
        return displayedMessages;
    return displayedMessages.length >= sessionMessages.length
        ? displayedMessages
        : sessionMessages;
}
export function mergeIncomingProjectMessages(local, incoming, incremental) {
    if (!incoming.length)
        return local;
    if (!local.length)
        return incoming;
    if (!incremental) {
        if (incoming.length >= local.length)
            return incoming;
        const seen = new Set(incoming.map(messageKey).filter((key) => !!key));
        const extras = local.filter((message) => {
            const key = messageKey(message);
            return !key || !seen.has(key);
        });
        return extras.length ? [...incoming, ...extras] : incoming;
    }
    const indexByKey = new Map();
    local.forEach((message, index) => {
        const key = messageKey(message);
        if (key)
            indexByKey.set(key, index);
    });
    let changed = false;
    const next = [...local];
    for (const message of incoming) {
        const key = messageKey(message);
        if (!key) {
            next.push(message);
            changed = true;
            continue;
        }
        const index = indexByKey.get(key);
        if (index == null) {
            indexByKey.set(key, next.length);
            next.push(message);
            changed = true;
            continue;
        }
        const current = next[index];
        if (projectMessageNeedsUpdate(current, message)) {
            next[index] = mergeProjectMessage(current, message);
            changed = true;
        }
    }
    return changed ? next : local;
}
export function applyProjectChatSync(local, sync, opts) {
    const protect = new Set(opts.protectedIds ?? []);
    const nextIds = new Set(sync.sessionIds);
    const gone = new Set();
    if (sync.goneSessionId)
        gone.add(sync.goneSessionId);
    if (sync.completeWindow) {
        for (const session of local) {
            if (!nextIds.has(session.id) && !protect.has(session.id))
                gone.add(session.id);
        }
    }
    else {
        for (const id of opts.previousSessionIds) {
            if (!nextIds.has(id) && !protect.has(id))
                gone.add(id);
        }
    }
    const keptLocal = local.filter((session) => !gone.has(session.id));
    let merged = mergeRemoteChatSessions(keptLocal, sync.sessions, protect);
    merged = applyProjectPins(merged, sync.pinnedSessionIds);
    merged = sortProjectSessions(merged.filter((session) => !gone.has(session.id)));
    const activeId = opts.activeSessionId ?? null;
    const incoming = sync.messages ?? [];
    const messageSessionId = sync.messageSessionId ?? activeId;
    let activeMessages = null;
    if (activeId &&
        messageSessionId === activeId &&
        incoming.length &&
        !protect.has(activeId)) {
        const current = merged.find((session) => session.id === activeId);
        const localMsgs = pickProjectSyncMessageBase(current?.messages ?? [], opts.activeLocalMessages);
        const mergedMsgs = mergeIncomingProjectMessages(localMsgs, incoming, opts.incrementalMessages === true && localMsgs.length > 0);
        if (mergedMsgs !== localMsgs) {
            activeMessages = mergedMsgs;
            merged = merged.map((session) => session.id === activeId
                ? {
                    ...session,
                    messages: mergedMsgs,
                    messageCount: Math.max(session.messageCount ?? 0, mergedMsgs.length),
                }
                : session);
        }
    }
    return { sessions: merged, activeMessages };
}
