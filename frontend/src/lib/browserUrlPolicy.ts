export type BrowserUrlKind = "navigation" | "image" | "media" | "download";

const SAFE_RASTER_DATA_URL =
  /^data:image\/(?:png|jpe?g|gif|webp|avif);(?:base64,|charset=[^,;]+;base64,)/i;
const SAFE_MEDIA_DATA_URL =
  /^data:(?:audio|video)\/(?:mpeg|mp3|mp4|ogg|wav|webm|aac|flac);(?:base64,|charset=[^,;]+;base64,)/i;

function defaultBaseUrl(): string {
  if (typeof window !== "undefined" && window.location?.href) return window.location.href;
  return "http://localhost/";
}

function isSameOrigin(url: URL, base: URL): boolean {
  return url.origin === base.origin;
}

function isLoopbackHost(hostname: string): boolean {
  const host = hostname.toLowerCase().replace(/^\[|\]$/g, "");
  return host === "localhost" || host === "127.0.0.1" || host === "::1";
}

export function safeBrowserUrl(
  value: string | null | undefined,
  kind: BrowserUrlKind,
  baseUrl = defaultBaseUrl(),
): string | null {
  if (!value) return null;
  const trimmed = value.trim();
  if (!trimmed || /[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/.test(trimmed)) return null;

  if (trimmed.toLowerCase().startsWith("data:")) {
    if ((kind === "image" || kind === "download") && SAFE_RASTER_DATA_URL.test(trimmed)) {
      return trimmed;
    }
    if ((kind === "media" || kind === "download") && SAFE_MEDIA_DATA_URL.test(trimmed)) {
      return trimmed;
    }
    return null;
  }

  let base: URL;
  let parsed: URL;
  try {
    base = new URL(baseUrl);
    parsed = new URL(trimmed, base);
  } catch {
    return null;
  }
  if (parsed.username || parsed.password) return null;

  if (parsed.protocol === "blob:") {
    return kind === "image" || kind === "media" || kind === "download" ? trimmed : null;
  }
  if (parsed.protocol === "mailto:" || parsed.protocol === "tel:") {
    return kind === "navigation" ? trimmed : null;
  }
  if (parsed.protocol === "https:") return trimmed;
  if (parsed.protocol === "http:") {
    if (isSameOrigin(parsed, base)) return trimmed;
    if (isLoopbackHost(parsed.hostname) && isLoopbackHost(base.hostname)) return trimmed;
  }
  return null;
}

export function inertBrowserUrl(
  value: string | null | undefined,
  kind: BrowserUrlKind,
): string {
  return safeBrowserUrl(value, kind) ?? "#";
}

export function openSafeUrlInNewTab(
  value: string | null | undefined,
  kind: BrowserUrlKind,
): boolean {
  const href = safeBrowserUrl(value, kind);
  if (!href || typeof document === "undefined") return false;
  const anchor = document.createElement("a");
  anchor.href = href;
  anchor.target = "_blank";
  anchor.rel = "noopener noreferrer";
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  return true;
}
