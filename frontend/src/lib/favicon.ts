/** Apply Alpharouter brand favicon (cache-bust when mark assets change). */
const BRAND_FAVICON_SVG = "/favicon.svg?v=4";
const BRAND_FAVICON_ICO = "/favicon.ico?v=4";
/** iOS needs a PNG for the Home Screen icon; with an SVG it uses a screenshot of the page. */
export const APPLE_TOUCH_ICON = "/icons/apple-touch-icon.png";

const ICON_SELECTOR =
  'link[rel="icon"], link[rel="shortcut icon"], link[rel="apple-touch-icon"], link[rel="mask-icon"]';

export function applyBlankFavicon(): void {
  document.head.querySelectorAll(ICON_SELECTOR).forEach((node) => node.remove());

  const svg = document.createElement("link");
  svg.rel = "icon";
  svg.type = "image/svg+xml";
  svg.href = BRAND_FAVICON_SVG;
  document.head.appendChild(svg);

  const ico = document.createElement("link");
  ico.rel = "icon";
  ico.type = "image/x-icon";
  ico.href = BRAND_FAVICON_ICO;
  document.head.appendChild(ico);

  const shortcut = document.createElement("link");
  shortcut.rel = "shortcut icon";
  shortcut.href = BRAND_FAVICON_ICO;
  document.head.appendChild(shortcut);

  const touch = document.createElement("link");
  touch.rel = "apple-touch-icon";
  touch.href = APPLE_TOUCH_ICON;
  document.head.appendChild(touch);
}
