/**
 * Injected into a page only when the user asks (chrome.scripting), never
 * declared for every site. It runs in an isolated world: the page's own
 * scripts cannot see or call anything defined here. It reads the page, and
 * acts in it for the browser agent; it never touches the extension's storage
 * or tokens.
 */

import { extractPage, isBlockDisplayed, isRendered, isTextRendered, type PageExtract } from "./extract";
import { runAgentCall } from "./runtime";
import type { Result } from "./agent";

type ContentApi = {
  extract: (limits: { maxChars: number; maxSelectionChars: number }) => PageExtract;
  /** One call from the side panel's agent: which action, with which arguments. */
  agent: (method: unknown, args: unknown) => Promise<Result>;
};

/** The overlay's Stop, to the side panel; a panel that has closed is not an error. */
function sendStop(message: { type: "agent-stop"; run: string }): void {
  try {
    void chrome.runtime.sendMessage(message)?.catch?.(() => undefined);
  } catch {
    // The extension was reloaded: nobody is listening.
  }
}

const scope = globalThis as typeof globalThis & { __alpharouter?: ContentApi };

// Every injection puts this copy in place, over whatever is there: a copy an
// older version of the extension left in the page must never be what reads it.
scope.__alpharouter = {
  extract: (limits) =>
    extractPage(document, {
      maxChars: limits.maxChars,
      maxSelectionChars: limits.maxSelectionChars,
      isVisible: isRendered,
      isTextVisible: isTextRendered,
      isBlock: isBlockDisplayed,
    }),
  agent: (method, args) => runAgentCall(document, method, args, isRendered, sendStop),
};
