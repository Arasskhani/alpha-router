import { isPrivateBlobRef, resolvePrivateMediaUrlForApi } from "./privateMediaStore";
import { isAutoRouterExternalId } from "./chatModels";
import {
  ATTACHMENT_MESSAGE_PREFIX,
  AUDIO_MESSAGE_PREFIX,
} from "./chatMarkers";

export { ATTACHMENT_MESSAGE_PREFIX, AUDIO_MESSAGE_PREFIX } from "./chatMarkers";

export type ProcessedAttachment = {
  name: string;
  kind: "image" | "document";
  mime_type: string;
  url: string;
  data_url?: string;
  text?: string;
};

export type AttachmentMessagePayload = {
  userText: string;
  attachments: ProcessedAttachment[];
};

export const MAX_ATTACHMENTS = 5;

const BLOCKED_EXTENSIONS = new Set([
  "apk", "app", "application", "asp", "aspx", "bat", "bin", "cab", "cmd", "com", "cpl", "crt",
  "deb", "dll", "dmg", "exe", "gadget", "hta", "htm", "html", "inf", "ins", "iso", "jar", "js",
  "jse", "jsp", "lnk", "mjs", "msc", "msi", "msp", "mst", "php", "pif", "ps1", "psm1", "py",
  "pyc", "pyo", "pyw", "rb", "reg", "rpm", "scr", "sh", "svg", "svgz", "swf", "tar", "vb", "vbe",
  "vbs", "ws", "wsc", "wsf", "wsh", "xhtml", "7z", "rar", "zip", "gz", "bz2", "xz", "z", "url",
  "desktop", "torrent", "wasm", "elf", "so", "dylib", "sys", "drv", "ocx", "xht", "shtml", "mht",
  "mhtml",
]);

const ALLOWED_IMAGE = new Set([
  "jpg", "jpeg", "png", "gif", "webp", "bmp", "tif", "tiff", "heic", "heif", "avif", "ico",
]);

const ALLOWED_DOCUMENT = new Set([
  "pdf", "doc", "docx", "xls", "xlsx", "xlsm", "csv", "tsv", "txt", "text", "md", "markdown",
  "rtf", "odt", "ods", "odp", "ppt", "pptx", "json", "yaml", "yml", "xml", "log", "ini", "cfg",
  "conf", "tex", "rst", "sql", "toml", "properties",
]);

const ALLOWED = new Set([...ALLOWED_IMAGE, ...ALLOWED_DOCUMENT]);

function fileExtensions(name: string): string[] {
  const parts = name.toLowerCase().split(".");
  if (parts.length < 2) return [];
  return parts.slice(1);
}

export function validateAttachmentFile(file: File): void {
  const parts = fileExtensions(file.name);
  if (!parts.length) {
    throw new Error("Files must have a recognized extension.");
  }
  for (const ext of parts) {
    if (BLOCKED_EXTENSIONS.has(ext)) {
      throw new Error(`File type ".${ext}" is not allowed for security reasons.`);
    }
  }
  const ext = parts[parts.length - 1];
  if (!ALLOWED.has(ext)) {
    throw new Error(`File type ".${ext}" is not supported. Use images (not SVG) or text documents.`);
  }
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

export function promptTextFromUserContent(content: string): string {
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
    if (attach.attachments.some((a) => a.kind === "document")) return false;
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

export const ATTACHMENT_ACCEPT = [
  ...ALLOWED_IMAGE,
  ...ALLOWED_DOCUMENT,
].map((e) => `.${e}`).join(",");

const LOCAL_TEXT_EXTENSIONS = new Set([
  "txt", "text", "md", "markdown", "csv", "tsv", "json", "yaml", "yml", "xml", "log", "ini", "cfg", "conf", "tex", "rst", "sql", "toml", "properties",
]);

function readFileAsDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(new Error(`Could not read ${file.name}.`));
    reader.readAsDataURL(file);
  });
}

/** Process attachments in the browser for Private Mode (no server upload). */
export async function processAttachmentFilesLocally(files: File[]): Promise<ProcessedAttachment[]> {
  const out: ProcessedAttachment[] = [];
  for (const file of files) {
    validateAttachmentFile(file);
    const parts = file.name.toLowerCase().split(".");
    const ext = parts[parts.length - 1] || "";
    if (ALLOWED_IMAGE.has(ext)) {
      const data_url = await readFileAsDataUrl(file);
      out.push({
        name: file.name,
        kind: "image",
        mime_type: file.type || `image/${ext}`,
        url: data_url,
        data_url,
      });
      continue;
    }
    if (LOCAL_TEXT_EXTENSIONS.has(ext)) {
      const text = await file.text();
      out.push({
        name: file.name,
        kind: "document",
        mime_type: file.type || "text/plain",
        url: "",
        text,
      });
      continue;
    }
    throw new Error(
      `Private Mode: "${file.name}" cannot be processed locally. Use an image or plain-text file, or turn off Private Mode.`,
    );
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

  const docs = attach.attachments.filter((a) => a.kind === "document");
  const images = attach.attachments.filter((a) => a.kind === "image");
  let text = attach.userText.trim();
  for (const doc of docs) {
    if (doc.text) {
      text += `${text ? "\n\n" : ""}--- ${doc.name} ---\n${doc.text}`;
    }
  }
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
    const url =
      isPrivateBlobRef(raw) || raw.startsWith("blob:")
        ? await resolvePrivateMediaUrlForApi(raw)
        : raw;
    parts.push({ type: "image_url", image_url: { url } });
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

  const docs = attach.attachments.filter((a) => a.kind === "document");
  const images = attach.attachments.filter((a) => a.kind === "image");
  let text = attach.userText.trim();
  for (const doc of docs) {
    if (doc.text) {
      text += `${text ? "\n\n" : ""}--- ${doc.name} ---\n${doc.text}`;
    }
  }
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
