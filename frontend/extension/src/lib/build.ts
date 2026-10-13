/**
 * Which build of the extension this code came from: a hash of its sources,
 * set by scripts/build-extension.mjs for the side panel and content.js alike
 * ("dev" when nothing sets it, as in the tests). The panel uses content.js
 * already in a page only when it is this build's.
 */

declare const __ALPHAROUTER_BUILD__: string | undefined;

export const EXTENSION_BUILD: string = typeof __ALPHAROUTER_BUILD__ === "string" ? __ALPHAROUTER_BUILD__ : "dev";
