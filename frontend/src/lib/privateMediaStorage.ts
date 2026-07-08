/** Compact / hydrate Private Mode chat messages — blobs in IndexedDB, refs in localStorage. */

import {
  attachmentMessage,
  readAttachmentMessage,
  type ProcessedAttachment,
} from "./chatAttachments";
import { buildImageMessage, IMAGE_MESSAGE_PREFIX, type ImagePayload } from "./chatImage";
import type { ChatMessage, ChatSession } from "./chatStorage";
import {
  isPrivateBlobRef,
  resolvePrivateBlobRef,
  storePrivateMediaUrl,
} from "./privateMediaStore";

function parseImageMessage(content: string): ImagePayload | null {
  if (!content.startsWith(IMAGE_MESSAGE_PREFIX)) return null;
  try {
    return JSON.parse(content.slice(IMAGE_MESSAGE_PREFIX.length)) as ImagePayload;
  } catch {
    return null;
  }
}

function shouldOffloadMediaUrl(url: string | undefined): boolean {
  if (!url) return false;
  const trimmed = url.trim();
  if (!trimmed || isPrivateBlobRef(trimmed)) return false;
  return trimmed.startsWith("data:") || trimmed.startsWith("blob:");
}

async function compactMediaUrl(url: string | undefined): Promise<string | undefined> {
  if (!url?.trim()) return url;
  if (!shouldOffloadMediaUrl(url)) return url;
  return storePrivateMediaUrl(url);
}

async function compactPrivateImageContent(content: string): Promise<string> {
  const payload = parseImageMessage(content);
  if (!payload) return content;
  const url = await compactMediaUrl(payload.url);
  const reference_image = payload.reference_image
    ? await compactMediaUrl(payload.reference_image)
    : payload.reference_image;
  if (url === payload.url && reference_image === payload.reference_image) return content;
  return buildImageMessage({ ...payload, url: url || payload.url, reference_image });
}

async function compactPrivateAttachmentContent(content: string): Promise<string> {
  const attach = readAttachmentMessage(content);
  if (!attach) return content;
  let changed = false;
  const attachments: ProcessedAttachment[] = [];
  for (const att of attach.attachments) {
    if (att.kind !== "image") {
      attachments.push(att);
      continue;
    }
    const raw = att.data_url || att.url;
    if (!shouldOffloadMediaUrl(raw)) {
      attachments.push({ ...att, data_url: undefined });
      continue;
    }
    const ref = await storePrivateMediaUrl(raw);
    attachments.push({ ...att, url: ref, data_url: undefined });
    changed = true;
  }
  if (!changed) return content;
  return attachmentMessage({ userText: attach.userText, attachments });
}

async function compactPrivateMessageContent(content: string): Promise<string> {
  if (content.startsWith(IMAGE_MESSAGE_PREFIX)) {
    return compactPrivateImageContent(content);
  }
  return compactPrivateAttachmentContent(content);
}

async function hydrateMediaUrl(url: string | undefined): Promise<string | undefined> {
  if (!url?.trim()) return url;
  const trimmed = url.trim();
  if (trimmed.startsWith("data:")) {
    const ref = await storePrivateMediaUrl(trimmed);
    return resolvePrivateBlobRef(ref);
  }
  if (isPrivateBlobRef(trimmed)) {
    return resolvePrivateBlobRef(trimmed);
  }
  return url;
}

async function hydratePrivateImageContent(content: string): Promise<string> {
  const payload = parseImageMessage(content);
  if (!payload) return content;
  const url = await hydrateMediaUrl(payload.url);
  const reference_image = payload.reference_image
    ? await hydrateMediaUrl(payload.reference_image)
    : payload.reference_image;
  if (url === payload.url && reference_image === payload.reference_image) return content;
  return buildImageMessage({ ...payload, url: url || payload.url, reference_image });
}

async function hydratePrivateAttachmentContent(content: string): Promise<string> {
  const attach = readAttachmentMessage(content);
  if (!attach) return content;
  let changed = false;
  const attachments: ProcessedAttachment[] = [];
  for (const att of attach.attachments) {
    if (att.kind !== "image") {
      attachments.push(att);
      continue;
    }
    const raw = att.data_url || att.url;
    const resolved = await hydrateMediaUrl(raw);
    if (resolved && resolved !== raw) {
      attachments.push({ ...att, url: resolved, data_url: undefined });
      changed = true;
    } else {
      attachments.push(att);
    }
  }
  if (!changed) return content;
  return attachmentMessage({ userText: attach.userText, attachments });
}

async function hydratePrivateMessageContent(content: string): Promise<string> {
  if (content.startsWith(IMAGE_MESSAGE_PREFIX)) {
    return hydratePrivateImageContent(content);
  }
  return hydratePrivateAttachmentContent(content);
}

/** Move inline media bytes to IndexedDB; keep only small refs in session JSON. */
export async function compactPrivateSessionsForStorage(
  sessions: ChatSession[],
): Promise<ChatSession[]> {
  const out: ChatSession[] = [];
  for (const session of sessions) {
    if (!session.privateMode) {
      out.push(session);
      continue;
    }
    const messages: ChatMessage[] = [];
    for (const msg of session.messages) {
      messages.push({
        ...msg,
        content: await compactPrivateMessageContent(msg.content),
      });
    }
    out.push({ ...session, messages });
  }
  return out;
}

/** Replace stored private blob refs with in-memory blob: URLs for rendering. */
export async function hydratePrivateSessionsFromStorage(
  sessions: ChatSession[],
): Promise<ChatSession[]> {
  const out: ChatSession[] = [];
  for (const session of sessions) {
    if (!session.privateMode) {
      out.push(session);
      continue;
    }
    const messages: ChatMessage[] = [];
    for (const msg of session.messages) {
      messages.push({
        ...msg,
        content: await hydratePrivateMessageContent(msg.content),
      });
    }
    out.push({ ...session, messages });
  }
  return out;
}

/** True when compact would rewrite legacy inline base64 in storage JSON. */
export function privateSessionsNeedStorageMigration(sessions: ChatSession[]): boolean {
  for (const session of sessions) {
    if (!session.privateMode) continue;
    for (const msg of session.messages) {
      const image = parseImageMessage(msg.content);
      if (image && shouldOffloadMediaUrl(image.url)) return true;
      if (image?.reference_image && shouldOffloadMediaUrl(image.reference_image)) return true;
      const attach = readAttachmentMessage(msg.content);
      if (attach) {
        for (const att of attach.attachments) {
          if (att.kind === "image" && shouldOffloadMediaUrl(att.data_url || att.url)) return true;
        }
      }
    }
  }
  return false;
}
