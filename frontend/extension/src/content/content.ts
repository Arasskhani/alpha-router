/**
 * Injected into a page only when the user asks (chrome.scripting), never
 * declared for every site. It runs in an isolated world: the page's own
 * scripts cannot see or call anything defined here. It reads; it never
 * touches the extension's storage or tokens.
 */

import { extractPage, isRendered, isTextRendered, type PageExtract } from "./extract";

type ContentApi = {
  extract: (limits: { maxChars: number; maxSelectionChars: number }) => PageExtract;
};

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
    }),
};
