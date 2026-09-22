/**
 * Which files a person may attach — the operator's policy, mirrored in the browser.
 *
 * The server (`backend/app/services/upload_file_policy.py`) is the authority: it
 * refuses a file at upload time and its message is shown as-is. The client runs
 * the same name rules first so a refusal is immediate and does not cost an
 * upload. When the policy could not be fetched the pre-check refuses nothing
 * but a name without an extension and lets the server decide.
 */
import { api } from "../api";

export type AttachmentPolicy = {
  mode: "blocklist" | "allowlist";
  blocked: Set<string>;
  allowed: Set<string>;
  maxAttachments: number;
  maxUploadMb: number;
};

export type AttachmentKind = "image" | "video" | "audio" | "document" | "file";

export type FileNameClassification =
  | { ok: true; ext: string; kind: AttachmentKind }
  | { ok: false; reason: string };

type AttachmentPolicyWire = {
  mode?: string;
  blocked?: string[];
  allowed?: string[];
  max_attachments?: number;
  max_upload_mb?: number;
};

/** The four kinds the platform can parse or play. Kind detection only — not an allowlist. */
export const IMAGE_EXTENSIONS = new Set([
  "jpg", "jpeg", "png", "gif", "webp", "bmp", "tif", "tiff", "heic", "heif", "avif", "ico",
]);

export const VIDEO_EXTENSIONS = new Set([
  "mp4", "m4v", "mov", "mkv", "webm", "avi", "wmv", "flv", "mpeg", "mpg", "mpe", "mp2", "m2v",
  "3gp", "3g2", "ts", "m2ts", "mts", "ogv", "vob",
]);

export const AUDIO_EXTENSIONS = new Set([
  "mp3", "ogg", "oga", "opus", "wav", "flac", "aac", "m4a", "wma", "aiff", "aif", "aifc",
  "mid", "midi", "weba", "amr", "caf",
]);

const DOCUMENT_EXTENSIONS = new Set([
  "pdf", "doc", "docx", "xls", "xlsx", "xlsm", "csv", "tsv", "txt", "text", "md", "markdown",
  "rtf", "odt", "ods", "odp", "ppt", "pptx", "json", "yaml", "yml", "xml", "log", "ini", "cfg",
  "conf", "tex", "rst", "sql", "toml", "properties",
]);

const POLICY_TTL_MS = 60_000;

let cached: { at: number; policy: AttachmentPolicy } | null = null;
let inFlight: Promise<AttachmentPolicy | null> | null = null;

function normalizeList(values: unknown): Set<string> {
  const out = new Set<string>();
  if (!Array.isArray(values)) return out;
  for (const v of values) {
    if (typeof v !== "string") continue;
    const ext = v.trim().toLowerCase().replace(/^\.+/, "");
    if (ext) out.add(ext);
  }
  return out;
}

function policyFromWire(raw: AttachmentPolicyWire): AttachmentPolicy {
  return {
    mode: raw.mode === "allowlist" ? "allowlist" : "blocklist",
    blocked: normalizeList(raw.blocked),
    allowed: normalizeList(raw.allowed),
    maxAttachments: Number.isFinite(raw.max_attachments) && (raw.max_attachments as number) > 0
      ? Math.floor(raw.max_attachments as number)
      : 5,
    maxUploadMb: Number.isFinite(raw.max_upload_mb) && (raw.max_upload_mb as number) > 0
      ? (raw.max_upload_mb as number)
      : 25,
  };
}

/** The operator's policy, cached for a minute; null when it cannot be fetched. */
export function fetchAttachmentPolicy(): Promise<AttachmentPolicy | null> {
  if (cached && Date.now() - cached.at < POLICY_TTL_MS) return Promise.resolve(cached.policy);
  if (inFlight) return inFlight;
  inFlight = (async () => {
    try {
      const raw = await api<AttachmentPolicyWire>("/api/chat/attachment-policy");
      const policy = policyFromWire(raw || {});
      cached = { at: Date.now(), policy };
      return policy;
    } catch {
      return null;
    } finally {
      inFlight = null;
    }
  })();
  return inFlight;
}

export function resetAttachmentPolicyCache(): void {
  cached = null;
  inFlight = null;
}

/** Every suffix of the name, lower-cased, without the dots: "Report.PDF.exe" → ["pdf", "exe"]. */
export function fileNameSuffixes(name: string): string[] {
  const base = (name || "").trim().replace(/\\/g, "/").split("/").pop() || "";
  const parts = base.split(".");
  if (parts.length < 2) return [];
  return parts.slice(1).map((p) => p.trim().toLowerCase()).filter(Boolean);
}

function kindForExtension(ext: string): AttachmentKind {
  if (IMAGE_EXTENSIONS.has(ext)) return "image";
  if (VIDEO_EXTENSIONS.has(ext)) return "video";
  if (AUDIO_EXTENSIONS.has(ext)) return "audio";
  if (DOCUMENT_EXTENSIONS.has(ext)) return "document";
  return "file";
}

/**
 * The server's name rules: every suffix against the blocklist, then (allowlist
 * mode) the last suffix must be allowed. Same wording as the server. With no
 * policy in hand only a missing extension is refused — the server decides.
 */
export function classifyFileName(name: string, policy: AttachmentPolicy | null): FileNameClassification {
  const suffixes = fileNameSuffixes(name);
  if (!suffixes.length) return { ok: false, reason: "Files must have an extension." };
  const ext = suffixes[suffixes.length - 1];
  if (policy) {
    for (const s of suffixes) {
      if (policy.blocked.has(s)) {
        return { ok: false, reason: `File type ".${s}" is not allowed on this platform.` };
      }
    }
    if (policy.mode === "allowlist" && !policy.allowed.has(ext)) {
      return { ok: false, reason: `File type ".${ext}" is not on the list of allowed file types.` };
    }
  }
  return { ok: true, ext, kind: kindForExtension(ext) };
}

/** 1234 → "1.2 KB"; sizes the person reads beside a file name. */
export function formatFileSize(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) return "";
  if (bytes < 1024) return `${Math.round(bytes)} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let value = bytes / 1024;
  let i = 0;
  while (value >= 1024 && i < units.length - 1) {
    value /= 1024;
    i += 1;
  }
  return `${value >= 100 ? Math.round(value) : value.toFixed(1)} ${units[i]}`;
}
