/**
 * What the web tools did for an answer: the pages it searched up or read
 * (shown under the answer), and what is happening while they run.
 *
 * The server sends both on the turn's stream (`alpha_router.web_sources`,
 * `alpha_router.web_activity`) and keeps the sources with the saved answer
 * (`webSources`), so a reloaded chat shows them too.
 */

export type WebSource = { title: string; url: string };

const MAX_SOURCES = 20;

/** Only http(s) addresses become links: anything else from the stream is dropped. */
function safeUrl(value: unknown): string | null {
  if (typeof value !== "string" || !value.trim()) return null;
  try {
    const url = new URL(value);
    return url.protocol === "http:" || url.protocol === "https:" ? url.href : null;
  } catch {
    return null;
  }
}

export function readWebSources(value: unknown): WebSource[] | undefined {
  if (!Array.isArray(value)) return undefined;
  const sources: WebSource[] = [];
  for (const item of value) {
    if (!item || typeof item !== "object") continue;
    const raw = item as Record<string, unknown>;
    const url = safeUrl(raw.url);
    if (!url || sources.some((s) => s.url === url)) continue;
    const title = typeof raw.title === "string" && raw.title.trim() ? raw.title.trim() : url;
    sources.push({ title, url });
    if (sources.length >= MAX_SOURCES) break;
  }
  return sources.length ? sources : undefined;
}

/** The site's name for a source, without "www.". */
export function sourceHost(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return "";
  }
}

/** What the chat says while a web tool runs, or undefined for a frame that is not one. */
export function webActivityLabel(value: unknown): string | undefined {
  if (!value || typeof value !== "object") return undefined;
  const raw = value as Record<string, unknown>;
  if (raw.tool === "web_search") {
    const query = typeof raw.query === "string" ? raw.query.trim() : "";
    return query ? `Searching the web: ${query}` : "Searching the web";
  }
  if (raw.tool === "web_fetch") {
    const host = typeof raw.host === "string" && raw.host ? raw.host.replace(/^www\./, "") : "";
    return host ? `Reading ${host}` : "Reading a page";
  }
  return undefined;
}
