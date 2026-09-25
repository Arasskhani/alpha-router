/**
 * Which pages the extension may read: the browser's own limits, and the
 * administrator's site rules.
 *
 * The rules are checked here before anything is read, with the same meaning
 * the server gives them (backend/app/services/extension_settings.py), and the
 * server checks every page a request declares again: this copy of the rules
 * can be a few minutes old.
 */

export type SitePolicy = {
  allowed_sites: string[];
  blocked_sites: string[];
};

export type SiteRefusal = "site_blocked" | "site_not_allowed";

/** A page the extension could read, if the rules and the user allow it. */
export type ReadablePage = {
  /** `URL.hostname` without a trailing dot: lower-case, punycode, IPv6 in brackets. */
  host: string;
  origin: string;
  /** The match pattern Chrome grants per site, as in `chrome.permissions`. */
  pattern: string;
};

/**
 * Stores that refuse extensions on their pages whatever the permissions say,
 * so offering to read them would only fail.
 */
const BROWSER_STORES = ["chromewebstore.google.com", "microsoftedge.microsoft.com"];

function isBrowserStore(url: URL): boolean {
  if (BROWSER_STORES.includes(url.hostname)) return true;
  return url.hostname === "chrome.google.com" && url.pathname.startsWith("/webstore");
}

/** http(s) pages only: never chrome://, edge://, file:, about:, data:, javascript: or an extension's page. */
export function readablePage(rawUrl: string | undefined): ReadablePage | null {
  if (!rawUrl) return null;
  let url: URL;
  try {
    url = new URL(rawUrl);
  } catch {
    return null;
  }
  if (url.protocol !== "http:" && url.protocol !== "https:") return null;
  if (!url.hostname || url.username || url.password || isBrowserStore(url)) return null;
  // "example.com." is example.com: the rules, the label and the server all
  // name it without the dot. The origin keeps it, as Chrome grants it.
  return { host: url.hostname.replace(/\.$/, ""), origin: url.origin, pattern: `${url.origin}/*` };
}

/** `*.example.com` covers example.com and every subdomain, as in Chrome's match patterns. */
export function hostMatches(host: string, pattern: string): boolean {
  const name = host.toLowerCase().replace(/\.$/, "");
  if (pattern.startsWith("*.")) {
    const domain = pattern.slice(2);
    return name === domain || name.endsWith(`.${domain}`);
  }
  return name === pattern;
}

/**
 * Null when the site may be read; otherwise why not. Blocked always wins; a
 * non-empty allow list shuts out every other site, except this Alpharouter
 * itself.
 */
export function siteRefusal(host: string, policy: SitePolicy, serverHost: string | null): SiteRefusal | null {
  if (policy.blocked_sites.some((pattern) => hostMatches(host, pattern))) return "site_blocked";
  if (serverHost && host.toLowerCase() === serverHost.toLowerCase()) return null;
  if (policy.allowed_sites.length && !policy.allowed_sites.some((pattern) => hostMatches(host, pattern))) {
    return "site_not_allowed";
  }
  return null;
}
