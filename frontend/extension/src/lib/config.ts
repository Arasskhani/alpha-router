/**
 * Which Alpharouter server this copy of the extension belongs to.
 *
 * The server writes config.json into every copy it hands out (the ZIP and the
 * CRX), so nobody types an address. A copy built from source and loaded as it
 * is has an empty serverUrl and says so instead of guessing.
 */

export type ExtensionConfig = {
  serverUrl: string;
  serverName: string;
  extensionVersion: string;
};

const EMPTY: ExtensionConfig = { serverUrl: "", serverName: "Alpharouter", extensionVersion: "" };

let cached: Promise<ExtensionConfig> | null = null;

function clean(raw: unknown): ExtensionConfig {
  if (!raw || typeof raw !== "object") return EMPTY;
  const value = raw as Record<string, unknown>;
  const serverUrl = typeof value.serverUrl === "string" ? value.serverUrl.trim().replace(/\/+$/, "") : "";
  let origin = "";
  try {
    const parsed = new URL(serverUrl);
    if (parsed.protocol === "https:" || parsed.protocol === "http:") origin = parsed.origin;
  } catch {
    origin = "";
  }
  return {
    serverUrl: origin,
    serverName: typeof value.serverName === "string" && value.serverName.trim() ? value.serverName.trim() : EMPTY.serverName,
    extensionVersion: typeof value.extensionVersion === "string" ? value.extensionVersion : "",
  };
}

export function loadConfig(fetchImpl: typeof fetch = fetch): Promise<ExtensionConfig> {
  cached ??= fetchImpl(chrome.runtime.getURL("config.json"))
    .then((res) => (res.ok ? res.json() : null))
    .then(clean)
    .catch(() => EMPTY);
  return cached;
}

export async function serverUrl(): Promise<string> {
  const { serverUrl: url } = await loadConfig();
  if (!url) throw new Error("This copy of the extension belongs to no Alpharouter server. Download it from Settings → Extension.");
  return url;
}

/** For tests. */
export function resetConfigForTests(): void {
  cached = null;
}

export { clean as parseConfig };
