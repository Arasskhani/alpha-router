/**
 * Pure helpers for chat messages that used to live at the top of ChatPanel.tsx
 * (Phase 4.6 split). No React, no state — everything here is unit-testable.
 */
import type { ChatMessage } from "./chatStorage";
import type { TextDirection } from "./textDirection";
import type { ProcessedAttachment } from "./chatAttachments";
import { attachmentDisplayText, readAttachmentMessage } from "./chatAttachments";
import { IMAGE_MESSAGE_PREFIX, IMAGE_PENDING_MARKER, type ImagePayload } from "./chatImage";
import { VIDEO_MESSAGE_PREFIX, VIDEO_PENDING_MARKER, parseVideoMessage, type VideoPayload } from "./chatVideo";
import { SPEECH_MESSAGE_PREFIX, SPEECH_PENDING_MARKER, parseSpeechMessage, type SpeechPayload } from "./chatSpeech";
import { messageDirectionForText } from "./textDirection";
import { formatLocalDateTimeFromMs } from "./dateTime";
import { AUDIO_MESSAGE_PREFIX } from "./chatMarkers";

export type AudioPayload = { url: string; transcript: string };
export type QueuedPrompt = {
  id: string;
  text: string;
  attachments: ProcessedAttachment[];
};

export function shortModelName(name: string, id: string) {
  const n = name || id;
  return n.length > 28 ? `${n.slice(0, 26)}…` : n;
}

export function readAudioMessage(content: string): AudioPayload | null {
  if (content.startsWith(AUDIO_MESSAGE_PREFIX)) {
    try {
      return JSON.parse(content.slice(AUDIO_MESSAGE_PREFIX.length)) as AudioPayload;
    } catch {
      return null;
    }
  }
  return null;
}

/**
 * Remove a user prompt (and the assistant replies that follow it) from a
 * message list, identifying the prompt by its stable `clientMessageId`.
 *
 * `fallbackIndex` is only used when the target has no client id and the message
 * at that index still matches the target's role+content (defensive against the
 * list shifting under a background sync). Returns null when the target can no
 * longer be located safely, so callers can abort instead of deleting the wrong
 * thread.
 */
export function removePromptThreadFromMessages(
  source: ChatMessage[],
  target: ChatMessage,
  fallbackIndex?: number,
): ChatMessage[] | null {
  let i = -1;
  if (target.clientMessageId) {
    i = source.findIndex((m) => m.clientMessageId === target.clientMessageId);
  }
  if (i < 0 && target.sentAt != null) {
    i = source.findIndex((m) => m.role === "user" && m.sentAt === target.sentAt);
  }
  if (
    i < 0 &&
    fallbackIndex != null &&
    source[fallbackIndex]?.role === "user" &&
    source[fallbackIndex]?.content === target.content
  ) {
    i = fallbackIndex;
  }
  if (i < 0 || source[i]?.role !== "user") return null;
  const next = [...source];
  next.splice(i, 1);
  while (next[i]?.role === "assistant") {
    next.splice(i, 1);
  }
  return next;
}

export function promptTextFromUserContent(content: string): string {
  const attach = readAttachmentMessage(content);
  if (attach) {
    const text = attach.userText.trim();
    if (text) return text;
    if (attach.attachments.some((a) => a.kind === "image")) return "Edit this image";
    return attachmentDisplayText(attach);
  }
  const audio = readAudioMessage(content);
  if (audio?.transcript?.trim()) return audio.transcript.trim();
  return content;
}

export function displayTextForMessage(content: string): string {
  const attach = readAttachmentMessage(content);
  if (attach) return attachmentDisplayText(attach);
  const audio = readAudioMessage(content);
  if (audio?.transcript) return audio.transcript;
  const image = readImageMessage(content);
  if (image?.prompt?.trim()) return image.prompt.trim();
  const video = readVideoMessage(content);
  if (video?.prompt?.trim()) return video.prompt.trim();
  const speech = readSpeechMessage(content);
  if (speech?.prompt?.trim()) return speech.prompt.trim();
  return content;
}

export function messageDirectionForContent(content: string): TextDirection {
  if (
    content === IMAGE_PENDING_MARKER ||
    content.startsWith(IMAGE_MESSAGE_PREFIX) ||
    content === VIDEO_PENDING_MARKER ||
    content.startsWith(VIDEO_MESSAGE_PREFIX) ||
    content === SPEECH_PENDING_MARKER ||
    content.startsWith(SPEECH_MESSAGE_PREFIX)
  ) {
    return "ltr";
  }
  const attach = readAttachmentMessage(content);
  if (attach) {
    return messageDirectionForText(attach.userText || attachmentDisplayText(attach));
  }
  const audio = readAudioMessage(content);
  if (audio?.transcript) return messageDirectionForText(audio.transcript);
  return messageDirectionForText(displayTextForMessage(content));
}

export function readVideoMessage(content: string): VideoPayload | null {
  return parseVideoMessage(content);
}

export function readSpeechMessage(content: string): SpeechPayload | null {
  return parseSpeechMessage(content);
}

/** Last assistant slot is a speech placeholder still being generated. */
export function messagesHavePendingSpeech(messages: ChatMessage[]): boolean {
  const last = messages.at(-1);
  return last?.role === "assistant" && last.content === SPEECH_PENDING_MARKER;
}

/** Last assistant slot is a video placeholder still being generated. */
export function messagesHavePendingVideo(messages: ChatMessage[]): boolean {
  const last = messages.at(-1);
  return last?.role === "assistant" && last.content === VIDEO_PENDING_MARKER;
}

export function buildStoppedVideoMessages(
  messages: ChatMessage[],
  stoppedText = "Video generation stopped.",
): ChatMessage[] {
  const withoutPending = messages.filter((m) => m.content !== VIDEO_PENDING_MARKER);
  const last = withoutPending.at(-1);
  if (last?.role === "assistant" && last.content === stoppedText) return withoutPending;
  return [
    ...withoutPending,
    { role: "assistant", content: stoppedText, receivedAt: Date.now() },
  ];
}

export function readImageMessage(content: string): ImagePayload | null {
  if (content.startsWith(IMAGE_MESSAGE_PREFIX)) {
    try {
      return JSON.parse(content.slice(IMAGE_MESSAGE_PREFIX.length)) as ImagePayload;
    } catch {
      return null;
    }
  }
  return null;
}

export function newQueueId() {
  return `q-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
}

export function queueItemPreview(item: QueuedPrompt): string {
  if (item.attachments.length) {
    const names = item.attachments.map((a) => a.name).join(", ");
    const text = item.text.trim();
    return text ? `${text} · ${names}` : names;
  }
  return item.text.trim() || "(empty)";
}

export function extractMarkdownImage(content: string): { imageUrl: string | null; text: string } {
  const re = /!\[[^\]]*\]\((https?:\/\/[^\s)]+)\)/i;
  const m = content.match(re);
  if (!m) return { imageUrl: null, text: content };
  const cleaned = content.replace(re, "").replace(/\n{3,}/g, "\n\n").trim();
  return { imageUrl: m[1], text: cleaned };
}

/** CSV / Word / PDF actions only for real text replies (not image/audio/pending). */
export function isTextAssistantExportable(content: string): boolean {
  if (!content?.trim()) return false;
  if (content === IMAGE_PENDING_MARKER) return false;
  if (content === VIDEO_PENDING_MARKER) return false;
  if (content === SPEECH_PENDING_MARKER) return false;
  if (readImageMessage(content)) return false;
  if (readVideoMessage(content)) return false;
  if (readSpeechMessage(content)) return false;
  if (readAudioMessage(content)) return false;
  const md = extractMarkdownImage(content);
  if (md.imageUrl && !md.text.trim()) return false;
  return true;
}

function formatChatMessageTime(ts?: number): string | null {
  return formatLocalDateTimeFromMs(ts);
}

export function chatMessageInfoTitle(message: ChatMessage, role: "user" | "assistant", messages: ChatMessage[], index: number): string {
  if (role === "user") {
    const sent = formatChatMessageTime(message.sentAt);
    return sent ? `Sent: ${sent}` : "Send time not recorded for this message.";
  }
  let promptSent: string | null = null;
  for (let j = index - 1; j >= 0; j -= 1) {
    if (messages[j].role === "user") {
      promptSent = formatChatMessageTime(messages[j].sentAt);
      break;
    }
  }
  const received = formatChatMessageTime(message.receivedAt);
  const lines: string[] = [];
  if (promptSent) lines.push(`Prompt sent: ${promptSent}`);
  if (received) lines.push(`Response received: ${received}`);
  return lines.length ? lines.join("\n") : "Timing not recorded for this message.";
}

