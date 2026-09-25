/**
 * Answers built from pages a user shared from the browser extension.
 *
 * The server marks such an answer (`pageContext` on the message). Page text
 * is untrusted - whoever can put words on a page can ask the model to put an
 * image in its answer whose address carries the conversation away - so the
 * chat shows these answers' images as links, never loads them, and says which
 * sites the answer came from.
 *
 * A later answer in the same chat is marked too (`inherited`): the page is
 * still in the conversation the model reads, so it can still steer the model.
 */

export type SharedPages = {
  /** Hosts of the shared pages; may be empty when the server named none. */
  sites: string[];
  /** This answer shared no page itself; an earlier answer in the chat did. */
  inherited: boolean;
};

const MAX_SITES = 20;
const MAX_HOST_CHARS = 253;

/**
 * The server's `pageContext`, checked. Anything there at all counts as a mark:
 * the protection never hinges on the mark's shape, so an unreadable one still
 * keeps images from loading and only loses the site names.
 */
export function readSharedPages(value: unknown): SharedPages | undefined {
  if (value === undefined || value === null) return undefined;
  const mark = typeof value === "object" && !Array.isArray(value) ? (value as { sites?: unknown; inherited?: unknown }) : {};
  const sites = Array.isArray(mark.sites)
    ? mark.sites.filter((site): site is string => typeof site === "string" && site.length > 0 && site.length <= MAX_HOST_CHARS)
    : [];
  return { sites: sites.slice(0, MAX_SITES), inherited: mark.inherited === true };
}

function pagesOn(sites: string[], preposition: "on" | "from"): string {
  const [first, ...rest] = sites;
  if (!first) return "a shared page";
  if (rest.length === 0) return `a page ${preposition} ${first}`;
  if (rest.length === 1) return `pages ${preposition} ${first} and ${rest[0]}`;
  return `pages ${preposition} ${first} and ${rest.length} other sites`;
}

export function sharedPagesLabel(pages: SharedPages): string {
  return pages.inherited ? `In a chat with ${pagesOn(pages.sites, "from")}` : `From ${pagesOn(pages.sites, "on")}`;
}

/** Why the answer looks the way it does, for the label's tooltip. */
export function sharedPagesNote(pages: SharedPages): string {
  const why = pages.inherited
    ? "An earlier answer in this chat was built from a page shared from the browser extension."
    : "Built from a page shared from the browser extension.";
  return `${why} Its images are shown as links, and it is not used as memory.`;
}

/** How an answer's images are shown: an answer built from shared pages never loads one. */
export function answerImages(message: { pageContext?: SharedPages }): "load" | "link" {
  return message.pageContext ? "link" : "load";
}

/**
 * What the chat may read as one of its own media messages - a generated image
 * or video, an attachment, a recording. An answer built from shared pages has
 * none, whatever it says: the page may have told the model to write one, and
 * the chat would load its address.
 */
export function mediaContent(message: { content: string; pageContext?: SharedPages }): string {
  return answerImages(message) === "load" ? message.content : "";
}
