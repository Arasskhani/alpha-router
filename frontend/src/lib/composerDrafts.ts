/** Per-session composer drafts (in-memory only; lost on tab close / refresh). */

import type { ProcessedAttachment } from "./chatAttachments";
import type { TextDirection } from "./textDirection";

export type ComposerDraft = {
  text: string;
  direction: TextDirection;
  attachments: ProcessedAttachment[];
};

const drafts = new Map<string, ComposerDraft>();

export function getComposerDraft(sessionId: string): ComposerDraft | null {
  return drafts.get(sessionId) ?? null;
}

export function clearComposerDraft(sessionId: string): void {
  drafts.delete(sessionId);
}

export function syncComposerDraft(
  sessionId: string | null | undefined,
  text: string,
  direction: TextDirection,
  attachments: ProcessedAttachment[] = [],
): void {
  if (!sessionId) return;
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

export function cloneComposerAttachments(attachments: ProcessedAttachment[]): ProcessedAttachment[] {
  return attachments.map((a) => ({ ...a }));
}
