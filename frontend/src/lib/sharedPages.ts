/**
 * Answers built from pages a user shared from the browser extension, or from
 * the person's email.
 *
 * The server marks such an answer (`pageContext` on the message). Page text
 * is untrusted - whoever can put words on a page can ask the model to put an
 * image in its answer whose address carries the conversation away - so the
 * chat shows these answers' images as links, never loads them, and says which
 * sites the answer came from.
 *
 * A later answer in the same chat is marked too (`inherited`): the page is
 * still in the conversation the model reads, so it can still steer the model.
 * The chat does not wait for the server to say so: see `withSharedPageMarks`.
 *
 * Email is the same kind of text: anyone can send the person an email that
 * tells the model to write such an image, with the other emails it read in its
 * address. An answer for which a mail tool read email is marked `mailContext`
 * (`alpha_router.mail_context` while it streams, `mailContext` once stored)
 * and shown the same way, without a label: the chat already says which tools
 * ran. The email itself is not in the conversation later answers read (only
 * the answers are), so the mark is not carried on to them.
 */

export type SharedPages = {
  /** Hosts of the shared pages; may be empty when the server named none. */
  sites: string[];
  /** This answer shared no page itself; an earlier answer in the chat did. */
  inherited: boolean;
};

/** The server's mark on an answer for which a mail tool read email. */
export type MailContext = { read: true };

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

/**
 * The server's `mailContext` (or the stream's `mail_context`), checked. As with
 * `pageContext`, anything there at all counts as a mark.
 */
export function readMailContext(value: unknown): MailContext | undefined {
  return value === undefined || value === null ? undefined : { read: true };
}

/** The mark the chat puts on an answer that may be reading email while it streams. */
export const MAIL_READ: MailContext = { read: true };

/** `message` with the mail mark set, or without it (the key gone) when there is none. */
export function withMailContext<T extends { mailContext?: MailContext }>(message: T, mark: MailContext | undefined): T {
  if (mark) return message.mailContext ? message : { ...message, mailContext: MAIL_READ };
  if (!("mailContext" in message)) return message;
  const { mailContext: _dropped, ...rest } = message;
  return rest as T;
}

/**
 * The chat's messages with every answer that follows an answer built from
 * shared pages marked as one too (`inherited`, with the earlier answers'
 * sites), whether or not the server's mark has reached it.
 *
 * The server marks such an answer when it saves it, but the chat has it
 * before that: its placeholder, every update while it streams, and a local
 * copy kept over the server's never carry the mark, although the page is
 * already in the conversation the model reads. An answer's own mark is kept
 * as it is. Returns `messages` itself when no answer needs a mark.
 */
export function withSharedPageMarks<T extends { role: string; pageContext?: SharedPages }>(messages: T[]): T[] {
  let sites: string[] | null = null;
  let changed = false;
  const marked = messages.map((message) => {
    if (message.role !== "assistant") return message;
    if (message.pageContext) {
      const seen: string[] = sites ?? [];
      sites = [...seen, ...message.pageContext.sites.filter((site) => !seen.includes(site))].slice(0, MAX_SITES);
      return message;
    }
    if (sites === null) return message;
    changed = true;
    return { ...message, pageContext: { sites: [...sites], inherited: true } };
  });
  return changed ? marked : messages;
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

/** The marks that make an answer's text untrusted: a shared page, or email a mail tool read. */
type UntrustedMarks = { pageContext?: SharedPages; mailContext?: MailContext };

/** Whether an answer was built from text someone else wrote (a shared page, an email). */
export function isUntrustedAnswer(message: UntrustedMarks): boolean {
  return Boolean(message.pageContext || message.mailContext);
}

/** How an answer's images are shown: an answer built from shared pages or email never loads one. */
export function answerImages(message: UntrustedMarks): "load" | "link" {
  return isUntrustedAnswer(message) ? "link" : "load";
}

/**
 * What the chat may read as one of its own media messages - a generated image
 * or video, an attachment, a recording. An answer built from shared pages or
 * email has none, whatever it says: the page or the email may have told the
 * model to write one, and the chat would load its address.
 */
export function mediaContent(message: { content: string } & UntrustedMarks): string {
  return answerImages(message) === "load" ? message.content : "";
}
