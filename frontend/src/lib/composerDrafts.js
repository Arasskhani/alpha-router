/** Per-session composer drafts (in-memory only; lost on tab close / refresh). */
const drafts = new Map();
export function getComposerDraft(sessionId) {
    return drafts.get(sessionId) ?? null;
}
export function clearComposerDraft(sessionId) {
    drafts.delete(sessionId);
}
export function syncComposerDraft(sessionId, text, direction, attachments = []) {
    if (!sessionId)
        return;
    const hasText = Boolean(text);
    const hasAttachments = attachments.length > 0;
    if (!hasText && !hasAttachments) {
        drafts.delete(sessionId);
        return;
    }
    drafts.set(sessionId, {
        text,
        direction,
        attachments: attachments.map((a) => ({ ...a })),
    });
}
export function cloneComposerAttachments(attachments) {
    return attachments.map((a) => ({ ...a }));
}
