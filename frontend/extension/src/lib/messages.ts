/**
 * Messages between the extension's own pages and its service worker.
 *
 * Every message has a `type`, and nothing is acted on that fails the check
 * for its type or comes from anywhere but this extension: the manifest has no
 * externally_connectable, and web pages cannot reach chrome.runtime at all,
 * but a check costs nothing and keeps it that way if a page ever could.
 */

export type ExtensionMessage =
  /** Tokens were saved or cleared (connected.html, the panel's Disconnect). */
  | { type: "auth-changed" }
  /** A right-click action or the shortcut left work for the panel. */
  | { type: "pending-action" }
  /** The agent's overlay on a page: the person watching pressed Stop for this run. */
  | { type: "agent-stop"; run: string };

const TYPES = new Set<ExtensionMessage["type"]>(["auth-changed", "pending-action", "agent-stop"]);
const RUN_ID = /^[A-Za-z0-9_-]{1,64}$/;

export function isExtensionMessage(value: unknown): value is ExtensionMessage {
  if (!value || typeof value !== "object") return false;
  const { type, run } = value as { type?: unknown; run?: unknown };
  if (typeof type !== "string" || !TYPES.has(type as ExtensionMessage["type"])) return false;
  return type !== "agent-stop" || (typeof run === "string" && RUN_ID.test(run));
}

/**
 * Sent by this extension's content script in the tab `tabId` - the agent's
 * overlay there. A web page cannot send it: it has no chrome.runtime.
 */
export function fromTabScript(sender: chrome.runtime.MessageSender, tabId: number): boolean {
  return sender.id === chrome.runtime.id && sender.tab?.id === tabId && !sender.url?.startsWith(chrome.runtime.getURL(""));
}

/**
 * Sent by one of this extension's own pages or its worker - not a content
 * script (whose sender URL is the web page's), not another extension.
 * connected.html runs in a tab, so a tab alone decides nothing.
 */
export function fromOwnPages(sender: chrome.runtime.MessageSender): boolean {
  return sender.id === chrome.runtime.id && Boolean(sender.url?.startsWith(chrome.runtime.getURL("")));
}

/** Tell the extension's other pages; a page that is not open is not an error. */
export async function broadcast(message: ExtensionMessage): Promise<void> {
  try {
    await chrome.runtime.sendMessage(message);
  } catch {
    // "Receiving end does not exist": nothing else is open.
  }
}
