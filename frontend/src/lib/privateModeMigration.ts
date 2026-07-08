import { api } from "../api";
import {
  attachmentMessage,
  readAttachmentMessage,
  type ProcessedAttachment,
} from "./chatAttachments";
import { buildImageMessage, IMAGE_MESSAGE_PREFIX, type ImagePayload } from "./chatImage";
import { type ChatMessage, type ChatSession } from "./chatStorage";
import { isNitroMediaFileUrl } from "./mediaUrl";
import { isPrivateBlobRef, resolvePrivateMediaUrlForApi } from "./privateMediaStore";

function parseImageMessage(content: string): ImagePayload | null {
  if (!content.startsWith(IMAGE_MESSAGE_PREFIX)) return null;
  try {
    return JSON.parse(content.slice(IMAGE_MESSAGE_PREFIX.length)) as ImagePayload;
  } catch {
    return null;
  }
}

async function storeMediaOnServer(opts: {
  kind: string;
  sessionId: string;
  dataUrl?: string;
  sourceUrl?: string;
  model?: string;
  prompt?: string;
  fileName?: string;
}): Promise<string> {
  const body: Record<string, string | undefined> = {
    kind: opts.kind,
    chat_session_id: opts.sessionId,
    model: opts.model,
    prompt: opts.prompt,
    file_name: opts.fileName,
  };
  if (opts.dataUrl) body.data_url = opts.dataUrl;
  if (opts.sourceUrl) body.source_url = opts.sourceUrl;
  const data = await api<{ url: string }>("/api/chat/media/store", {
    method: "POST",
    body: JSON.stringify(body),
  });
  return data.url;
}

async function migrateAttachment(att: ProcessedAttachment, sessionId: string, prompt: string) {
  if (isNitroMediaFileUrl(att.url)) return att;
  let dataUrl = att.data_url || (att.url.startsWith("data:") ? att.url : undefined);
  if (!dataUrl && (isPrivateBlobRef(att.url) || att.url.startsWith("blob:"))) {
    dataUrl = await resolvePrivateMediaUrlForApi(att.url);
  }
  const sourceUrl = !dataUrl && att.url.startsWith("http") ? att.url : undefined;
  if (!dataUrl && !sourceUrl) return att;
  const url = await storeMediaOnServer({
    kind: att.kind,
    sessionId,
    dataUrl,
    sourceUrl,
    prompt: prompt || att.name,
    fileName: att.name,
  });
  return { ...att, url, data_url: undefined };
}

async function migrateMessageContent(
  content: string,
  sessionId: string,
): Promise<{ content: string; changed: boolean }> {
  const image = parseImageMessage(content);
  if (image && !isNitroMediaFileUrl(image.url)) {
    let dataUrl = image.url.startsWith("data:") ? image.url : undefined;
    if (!dataUrl && (isPrivateBlobRef(image.url) || image.url.startsWith("blob:"))) {
      dataUrl = await resolvePrivateMediaUrlForApi(image.url);
    }
    const sourceUrl = !dataUrl && image.url.startsWith("http") ? image.url : undefined;
    if (dataUrl || sourceUrl) {
      const url = await storeMediaOnServer({
        kind: "image",
        sessionId,
        dataUrl,
        sourceUrl,
        model: image.model,
        prompt: image.prompt,
      });
      return {
        content: buildImageMessage({ ...image, url }),
        changed: true,
      };
    }
  }

  const attach = readAttachmentMessage(content);
  if (attach) {
    let changed = false;
    const attachments = await Promise.all(
      attach.attachments.map(async (att) => {
        const next = await migrateAttachment(att, sessionId, attach.userText || att.name);
        if (next.url !== att.url || next.data_url !== att.data_url) changed = true;
        return next;
      }),
    );
    if (changed) {
      return {
        content: attachmentMessage({ userText: attach.userText, attachments }),
        changed: true,
      };
    }
  }

  return { content, changed: false };
}

/** Upload local-only media from a private chat to server storage before leaving Private Mode. */
export async function migratePrivateSessionMediaToServer(session: ChatSession): Promise<ChatSession> {
  let anyChanged = false;
  const messages: ChatMessage[] = [];
  for (const msg of session.messages) {
    const { content, changed } = await migrateMessageContent(msg.content, session.id);
    messages.push(changed ? { ...msg, content } : msg);
    if (changed) anyChanged = true;
  }
  if (!anyChanged) return session;
  return { ...session, messages, updatedAt: Date.now() };
}
