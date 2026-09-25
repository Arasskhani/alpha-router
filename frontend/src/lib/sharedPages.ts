/**
 * Answers built from pages a user shared from the browser extension.
 *
 * The server marks such an answer (`pageContext` on the message). Page text
 * is untrusted - whoever can put words on a page can ask the model to put an
 * image in its answer whose address carries the conversation away - so the
 * chat shows these answers' images as links, never loads them, and says which
 * sites the answer came from.
 */

export type SharedPages = {
  /** Hosts of the shared pages; may be empty when the server named none. */
  sites: string[];
};

const MAX_SITES = 20;
const MAX_HOST_CHARS = 253;

/** The server's `pageContext`, checked. Any object counts as a mark: the protection never hinges on its details. */
export function readSharedPages(value: unknown): SharedPages | undefined {
  if (!value || typeof value !== "object" || Array.isArray(value)) return undefined;
  const raw = (value as { sites?: unknown }).sites;
  const sites = Array.isArray(raw)
    ? raw.filter((site): site is string => typeof site === "string" && site.length > 0 && site.length <= MAX_HOST_CHARS)
    : [];
  return { sites: sites.slice(0, MAX_SITES) };
}

export function sharedPagesLabel(pages: SharedPages): string {
  const [first, ...rest] = pages.sites;
  if (!first) return "From a shared page";
  if (rest.length === 0) return `From a page on ${first}`;
  if (rest.length === 1) return `From pages on ${first} and ${rest[0]}`;
  return `From pages on ${first} and ${rest.length} other sites`;
}

/** How an answer's images are shown: an answer built from shared pages never loads one. */
export function answerImages(message: { pageContext?: SharedPages }): "load" | "link" {
  return message.pageContext ? "link" : "load";
}
