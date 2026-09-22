import { isPrivateBlobRef, resolvePrivateMediaUrlForApi } from "./privateMediaStore";
import { isAutoRouterExternalId } from "./chatModels";
import { fetchAuthenticatedMediaBlob, isAlphaRouterMediaFileUrl } from "./mediaUrl";
import {
  ATTACHMENT_MESSAGE_PREFIX,
  AUDIO_MESSAGE_PREFIX,
} from "./chatMarkers";
import {
  AUDIO_EXTENSIONS,
  IMAGE_EXTENSIONS,
  VIDEO_EXTENSIONS,
  classifyFileName,
  fileNameSuffixes,
  formatFileSize,
  type AttachmentKind,
  type AttachmentPolicy,
} from "./attachmentPolicy";

export { ATTACHMENT_MESSAGE_PREFIX, AUDIO_MESSAGE_PREFIX } from "./chatMarkers";

export type ProcessedAttachment = {
  name: string;
  kind: AttachmentKind;
  mime_type: string;
  url: string;
  data_url?: string;
  /** Extracted text; null when the server stored the bytes but found no text in them. */
  text?: string | null;
  size_bytes?: number;
  /** True when no text could be extracted (the file is available for download and in the sandbox). */
  binary?: boolean;
};

export type AttachmentMessagePayload = {
  userText: string;
  attachments: ProcessedAttachment[];
};

export const DEFAULT_MAX_ATTACHMENTS = 5;

/**
 * Text formats the browser can read itself (Private Mode never uploads). The
 * second group is source code: blocked by default, but read as text with the
 * kind "file" once the operator unblocks it.
 */
const LOCAL_TEXT_EXTENSIONS = new Set([
  "txt", "text", "md", "markdown", "csv", "tsv", "json", "yaml", "yml", "xml", "log", "ini", "cfg", "conf", "tex", "rst", "sql", "toml", "properties",
  "py", "js", "mjs", "cjs", "ts", "tsx", "jsx", "sh", "bash", "zsh", "ps1", "rb", "php", "pl", "java", "kt", "scala",
  "c", "h", "cpp", "hpp", "cc", "cs", "go", "rs", "swift", "dart", "lua", "r", "css", "scss", "less", "env", "diff", "patch",
]);

export const PRIVATE_MODE_ATTACHMENT_MESSAGE =
  "In Private Mode only images, audio, video and text files can be attached.";

/**
 * The kind a name would be given, or null when the policy refuses it. Unknown
 * formats are "file". Without a policy nothing but a missing extension refuses.
 */
export function attachmentKindFromName(name: string, policy: AttachmentPolicy | null = null): AttachmentKind | null {
  const result = classifyFileName(name, policy);
  return result.ok ? result.kind : null;
}

export function canProcessAttachmentLocally(name: string): boolean {
  const kind = attachmentKindFromName(name);
  if (kind === "image" || kind === "video" || kind === "audio") return true;
  if (kind !== "document" && kind !== "file") return false;
  const ext = fileNameSuffixes(name).at(-1) || "";
  return LOCAL_TEXT_EXTENSIONS.has(ext);
}

/** Client pre-check with the server's own wording; the server still decides on upload. */
export function validateAttachmentFile(file: File, policy: AttachmentPolicy | null = null): void {
  const result = classifyFileName(file.name, policy);
  if (!result.ok) throw new Error(result.reason);
}

export function attachmentMessage(payload: AttachmentMessagePayload): string {
  return `${ATTACHMENT_MESSAGE_PREFIX}${JSON.stringify(payload)}`;
}

export function readAttachmentMessage(content: string): AttachmentMessagePayload | null {
  if (!content.startsWith(ATTACHMENT_MESSAGE_PREFIX)) return null;
  try {
    return JSON.parse(content.slice(ATTACHMENT_MESSAGE_PREFIX.length)) as AttachmentMessagePayload;
  } catch {
    return null;
  }
}

export function attachmentDisplayText(payload: AttachmentMessagePayload): string {
  const names = payload.attachments.map((a) => a.name).join(", ");
  const base = payload.userText.trim();
  if (base && names) return `${base}\n\n📎 ${names}`;
  if (base) return base;
  return names ? `📎 ${names}` : "";
}

/** Preserve attachment payloads when enqueueing chat prompts (including large data_url fields). */
export function cloneProcessedAttachments(attachments: ProcessedAttachment[]): ProcessedAttachment[] {
  return attachments.map((a) => ({ ...a }));
}

/** Drop inline image bytes from persisted chat JSON; media remains available via url. */
export function compactAttachmentMessageForStorage(content: string): string {
  const attach = readAttachmentMessage(content);
  if (!attach) return content;
  return attachmentMessage({
    userText: attach.userText,
    attachments: attach.attachments.map(({ data_url: _drop, ...rest }) => rest),
  });
}

export function compactChatMessagesForStorage<T extends { role: string; content: string }>(
  messages: T[],
): T[] {
  return messages.map((m) =>
    m.role === "user" ? { ...m, content: compactAttachmentMessageForStorage(m.content) } : m,
  );
}

export function referenceImageFromUserContent(content: string): string | undefined {
  const attach = readAttachmentMessage(content);
  if (!attach) return undefined;
  const img = attach.attachments.find((a) => a.kind === "image");
  const url = img?.data_url || img?.url;
  return url?.trim() || undefined;
}

/** Resolve private blob refs / blob URLs for image-to-image API calls. */
export async function resolveReferenceImageFromUserContent(
  content: string,
): Promise<string | undefined> {
  const raw = referenceImageFromUserContent(content);
  if (!raw) return undefined;
  if (isPrivateBlobRef(raw) || raw.startsWith("blob:")) {
    return resolvePrivateMediaUrlForApi(raw);
  }
  return raw;
}

/**
 * Image Generation tool routing:
 * - text-only → text-to-image when supported
 * - image attachment → image-to-image when supported
 * - prior assistant image → image-to-image only when the prompt implies editing that image
 * - documents / mixed docs → normal chat (never image gen)
 */

const IMAGE_EDIT_PROMPT_HINTS: RegExp[] = [
  /\bedit\b/i,
  /\bmodify\b/i,
  /\bchange\b/i,
  /\btransform\b/i,
  /\bretouch\b/i,
  /\bmake (the|this|it)\b/i,
  /\bupdate (the|this|it)\b/i,
  /\bsame (image|photo|picture)\b/i,
  /\bkeep (the|this) (composition|layout|pose|background)\b/i,
  /\b(in|on) (the|this) (image|photo|picture)\b/i,
  /تغییر/,
  /عوض\s*کن/,
  /ویرایش/,
  /همین\s*(عکس|تصویر)/,
  /(روی|در)\s*(این\s*)?(عکس|تصویر)/,
  /پس‌?زمینه/,
  /(عکس|تصویر).*(را|رو)\s*(تغییر|عوض)/,
  /(قسمت|بخش).*(عکس|تصویر)/,
];

function promptTextFromUserContent(content: string): string {
  const attach = readAttachmentMessage(content);
  if (attach) return attach.userText.trim();
  return content.trim();
}

/** True when the user likely wants to edit the previous generated image (not a fresh scene). */
export function promptImpliesImageEdit(prompt: string): boolean {
  const text = prompt.trim();
  if (!text) return false;
  return IMAGE_EDIT_PROMPT_HINTS.some((rx) => rx.test(text));
}

export function shouldRouteToImageGeneration(
  userContent: string,
  imageGenerationEnabled: boolean,
  supportsTextToImage: boolean,
  supportsImageToImage: boolean,
  priorAssistantImageUrl?: string,
): boolean {
  if (!imageGenerationEnabled) return false;
  const attach = readAttachmentMessage(userContent);
  if (attach) {
    if (attach.attachments.some((a) => a.kind !== "image")) {
      return false;
    }
    const image = attach.attachments.find((a) => a.kind === "image");
    const ref = (image?.data_url || image?.url || "").trim();
    if (ref) return supportsImageToImage;
    return false;
  }
  const prompt = promptTextFromUserContent(userContent);
  if (
    priorAssistantImageUrl &&
    supportsImageToImage &&
    promptImpliesImageEdit(prompt)
  ) {
    return true;
  }
  return supportsTextToImage;
}

function readFileAsDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(new Error(`Could not read ${file.name}.`));
    reader.readAsDataURL(file);
  });
}

/** Process attachments in the browser for Private Mode (no server upload). */
export async function processAttachmentFilesLocally(
  files: File[],
  policy: AttachmentPolicy | null = null,
): Promise<ProcessedAttachment[]> {
  const out: ProcessedAttachment[] = [];
  for (const file of files) {
    const result = classifyFileName(file.name, policy);
    if (!result.ok) throw new Error(result.reason);
    const { ext, kind } = result;
    if (IMAGE_EXTENSIONS.has(ext)) {
      const data_url = await readFileAsDataUrl(file);
      out.push({
        name: file.name,
        kind: "image",
        mime_type: file.type || `image/${ext}`,
        url: data_url,
        data_url,
        size_bytes: file.size,
      });
      continue;
    }
    if (VIDEO_EXTENSIONS.has(ext) || AUDIO_EXTENSIONS.has(ext)) {
      const data_url = await readFileAsDataUrl(file);
      const avKind = VIDEO_EXTENSIONS.has(ext) ? "video" : "audio";
      out.push({
        name: file.name,
        kind: avKind,
        mime_type: file.type || `${avKind}/${ext}`,
        url: data_url,
        data_url,
        size_bytes: file.size,
      });
      continue;
    }
    if (LOCAL_TEXT_EXTENSIONS.has(ext)) {
      // A text format the platform lists as a document, or an unblocked source
      // file such as .py: both are read as text; the kind tells them apart.
      const text = await file.text();
      out.push({
        name: file.name,
        kind: kind === "document" ? "document" : "file",
        mime_type: file.type || "text/plain",
        url: "",
        text,
        size_bytes: file.size,
      });
      continue;
    }
    throw new Error(PRIVATE_MODE_ATTACHMENT_MESSAGE);
  }
  return out;
}

type VisionModel = { id: string; name?: string; external_id?: string; supports_vision?: boolean };

export function modelSupportsVision(m?: VisionModel): boolean {
  if (!m) return false;
  // Prefer the backend catalog flag when available (Option B).
  if (typeof m.supports_vision === "boolean") return m.supports_vision;
  if (isAutoRouterExternalId(m.external_id)) return true;
  const v = `${m.external_id || ""} ${m.name || ""} ${m.id || ""}`.toLowerCase();
  if (isImageGenerationModel(v)) return false;
  return (
    v.includes("vision") ||
    v.includes("gpt-4o") ||
    v.includes("gpt-4.1") ||
    v.includes("gpt-4-turbo") ||
    v.includes("gpt-4") ||
    v.includes("claude-3") ||
    v.includes("claude-4") ||
    v.includes("claude-sonnet") ||
    v.includes("claude-opus") ||
    v.includes("claude-haiku") ||
    v.includes("gemini") ||
    v.includes("llava") ||
    v.includes("pixtral") ||
    v.includes("qwen-vl") ||
    v.includes("qwen2-vl")
  );
}

function isImageGenerationModel(v: string) {
  return (
    v.includes("dall") ||
    v.includes("flux") ||
    v.includes("sdxl") ||
    v.includes("stable-diffusion") ||
    v.includes("nanobanana") ||
    (v.includes("image") && !v.includes("vision"))
  );
}

export type ApiContentPart =
  | { type: "text"; text: string }
  | { type: "image_url"; image_url: { url: string } };

const mediaDataUrlCache = new Map<string, Promise<string>>();

export function imageUrlNeedsAuthResolve(url: string): boolean {
  const trimmed = (url || "").trim();
  if (!trimmed) return false;
  return isPrivateBlobRef(trimmed) || trimmed.startsWith("blob:") || isAlphaRouterMediaFileUrl(trimmed);
}

function blobToDataUrl(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(new Error("Could not read attached media."));
    reader.readAsDataURL(blob);
  });
}

async function resolveAttachmentImageUrlForApi(raw: string): Promise<string | undefined> {
  const trimmed = (raw || "").trim();
  if (!trimmed) return undefined;
  if (isPrivateBlobRef(trimmed) || trimmed.startsWith("blob:")) {
    return resolvePrivateMediaUrlForApi(trimmed);
  }
  if (!isAlphaRouterMediaFileUrl(trimmed)) return trimmed;
  const cached = mediaDataUrlCache.get(trimmed);
  if (cached) return cached;
  const pending = (async () => {
    const blob = await fetchAuthenticatedMediaBlob(trimmed);
    return blobToDataUrl(blob);
  })();
  mediaDataUrlCache.set(trimmed, pending);
  try {
    return await pending;
  } catch (err) {
    mediaDataUrlCache.delete(trimmed);
    throw err;
  }
}

function appendAvAttachmentNotes(
  text: string,
  attachments: ProcessedAttachment[],
): string {
  const videos = attachments.filter((a) => a.kind === "video");
  const audios = attachments.filter((a) => a.kind === "audio");
  let next = text;
  if (videos.length) {
    const names = videos.map((v) => v.name).join(", ");
    next += `${next ? "\n\n" : ""}[Attached video(s): ${names}]`;
  }
  if (audios.length) {
    const names = audios.map((a) => a.name).join(", ");
    next += `${next ? "\n\n" : ""}[Attached audio: ${names}]`;
  }
  return next;
}

function isTextBearingKind(a: ProcessedAttachment): boolean {
  return a.kind === "document" || a.kind === "file";
}

/**
 * What the model is told about documents and files: the extracted text when
 * there is any, otherwise a note naming the file and its size.
 */
export function attachmentFileNotes(attachments: ProcessedAttachment[]): string[] {
  const notes: string[] = [];
  for (const a of attachments) {
    if (!isTextBearingKind(a)) continue;
    if (a.text) {
      notes.push(`--- ${a.name} ---\n${a.text}`);
      continue;
    }
    if (a.binary || a.text === null) {
      const size = typeof a.size_bytes === "number" ? formatFileSize(a.size_bytes) : "";
      const detail = size ? `${size}, binary` : "binary";
      notes.push(
        `[Attached file "${a.name}" (${detail}): no text was extracted. ` +
          "It is available in the Code Interpreter workspace when that tool is enabled.]",
      );
    }
  }
  return notes;
}

function attachmentTextForModel(attach: AttachmentMessagePayload): string {
  let text = attach.userText.trim();
  for (const note of attachmentFileNotes(attach.attachments)) {
    text += `${text ? "\n\n" : ""}${note}`;
  }
  return appendAvAttachmentNotes(text, attach.attachments);
}

export async function buildApiMessageContentAsync(
  content: string,
  visionModel?: VisionModel,
): Promise<string | ApiContentPart[]> {
  const audio = content.startsWith(AUDIO_MESSAGE_PREFIX);
  if (audio) {
    try {
      const parsed = JSON.parse(content.slice(AUDIO_MESSAGE_PREFIX.length)) as { transcript?: string };
      if (parsed.transcript?.trim()) return parsed.transcript.trim();
    } catch {
      /* fall through */
    }
  }

  const attach = readAttachmentMessage(content);
  if (!attach) return content;

  const images = attach.attachments.filter((a) => a.kind === "image");
  let text = attachmentTextForModel(attach);
  if (!images.length) {
    return text || attachmentDisplayText(attach);
  }

  const useVision = modelSupportsVision(visionModel);
  if (!useVision) {
    const names = images.map((i) => i.name).join(", ");
    text += `${text ? "\n\n" : ""}[Attached image(s): ${names}. This model may not analyze images.]`;
    return text;
  }

  const parts: ApiContentPart[] = [];
  if (text) parts.push({ type: "text", text });
  for (const img of images) {
    const raw = img.data_url || img.url;
    if (!raw) continue;
    const url = await resolveAttachmentImageUrlForApi(raw);
    if (url) parts.push({ type: "image_url", image_url: { url } });
  }
  return parts.length ? parts : text;
}

export function buildApiMessageContent(
  content: string,
  visionModel?: VisionModel,
): string | ApiContentPart[] {
  const audio = content.startsWith(AUDIO_MESSAGE_PREFIX);
  if (audio) {
    try {
      const parsed = JSON.parse(content.slice(AUDIO_MESSAGE_PREFIX.length)) as { transcript?: string };
      if (parsed.transcript?.trim()) return parsed.transcript.trim();
    } catch {
      /* fall through */
    }
  }

  const attach = readAttachmentMessage(content);
  if (!attach) return content;

  const images = attach.attachments.filter((a) => a.kind === "image");
  let text = attachmentTextForModel(attach);
  if (!images.length) {
    return text || attachmentDisplayText(attach);
  }

  const useVision = modelSupportsVision(visionModel);
  if (!useVision) {
    const names = images.map((i) => i.name).join(", ");
    text += `${text ? "\n\n" : ""}[Attached image(s): ${names}. This model may not analyze images.]`;
    return text;
  }

  const parts: ApiContentPart[] = [];
  if (text) parts.push({ type: "text", text });
  for (const img of images) {
    const url = img.data_url || img.url;
    if (url) parts.push({ type: "image_url", image_url: { url } });
  }
  return parts.length ? parts : text;
}

export function hasApiContent(content: string | ApiContentPart[]): boolean {
  if (typeof content === "string") return !!content.trim();
  return content.length > 0;
}
