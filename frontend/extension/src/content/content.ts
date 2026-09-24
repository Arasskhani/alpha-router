/**
 * Injected into a page only when the user asks (chrome.scripting), never
 * declared for every site. It runs in an isolated world: the page's own
 * scripts cannot see or call anything defined here.
 */

type ContentApi = { version: number };

const scope = globalThis as typeof globalThis & { __alpharouter?: ContentApi };

// Injecting twice (a second question about the same page) must not reset it.
scope.__alpharouter ??= { version: 1 };
