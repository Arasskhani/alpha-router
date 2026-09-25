/**
 * Injected into a page only when the user asks (chrome.scripting), never
 * declared for every site. It runs in an isolated world: the page's own
 * scripts cannot see or call anything defined here. It reads; it never
 * touches the extension's storage or tokens.
 */

import { extractPage, isRendered, isTextRendered, type PageExtract } from "./extract";

/** Raised whenever what the panel calls here changes shape. */
const VERSION = 2;

type ContentApi = {
  version: number;
  extract: (limits: { maxChars: number; maxSelectionChars: number }) => PageExtract;
};

const scope = globalThis as typeof globalThis & { __alpharouter?: ContentApi };

// Injecting again for the next question keeps what is there, unless an older
// copy of the extension left it behind in this page.
if (scope.__alpharouter?.version !== VERSION) {
  scope.__alpharouter = {
    version: VERSION,
    extract: (limits) =>
      extractPage(document, {
        maxChars: limits.maxChars,
        maxSelectionChars: limits.maxSelectionChars,
        isVisible: isRendered,
        isTextVisible: isTextRendered,
      }),
  };
}
