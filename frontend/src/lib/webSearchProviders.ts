/**
 * The search services a web search connection can be, and the checks that keep a
 * search key and a model key from being swapped by mistake.
 *
 * The server refuses a connection whose provider belongs to the other kind; these
 * hints only warn, while the key is typed, when its shape says it belongs elsewhere.
 */

export type WebSearchProviderId = "brave" | "tavily" | "google_pse" | "searxng" | "duckduckgo";

export type WebSearchProvider = {
  id: WebSearchProviderId;
  label: string;
  /** One line on what it is and what it costs. */
  blurb: string;
  needsKey: boolean;
  /** The address of the organisation's own server (SearXNG). */
  needsBaseUrl: boolean;
  /** Google Programmable Search's search engine id. */
  needsEngineId: boolean;
  /** How a key of this service starts, when it always does. */
  keyPrefix?: string;
  /** A typical price of one search, in USD, to start the price field with. */
  suggestedPrice: number;
};

export const WEB_SEARCH_PROVIDERS: readonly WebSearchProvider[] = [
  {
    id: "brave",
    label: "Brave Search",
    blurb: "An independent search index with an API key; a free tier, then priced per search.",
    needsKey: true,
    needsBaseUrl: false,
    needsEngineId: false,
    keyPrefix: "BSA",
    suggestedPrice: 0.005,
  },
  {
    id: "tavily",
    label: "Tavily",
    blurb: "Search made for AI assistants: returns the relevant text of each page too.",
    needsKey: true,
    needsBaseUrl: false,
    needsEngineId: false,
    keyPrefix: "tvly-",
    suggestedPrice: 0.008,
  },
  {
    id: "google_pse",
    label: "Google Programmable Search",
    blurb: "Google results through a Programmable Search Engine: an API key and its search engine id (cx).",
    needsKey: true,
    needsBaseUrl: false,
    needsEngineId: true,
    keyPrefix: "AIza",
    suggestedPrice: 0.005,
  },
  {
    id: "searxng",
    label: "SearXNG (self-hosted)",
    blurb: "Your organisation's own SearXNG server: no key, and searches leave only through it.",
    needsKey: false,
    needsBaseUrl: true,
    needsEngineId: false,
    suggestedPrice: 0,
  },
  {
    id: "duckduckgo",
    label: "DuckDuckGo",
    blurb: "No key, read from its pages: free, but often rate limited. Best kept as the last fallback.",
    needsKey: false,
    needsBaseUrl: false,
    needsEngineId: false,
    suggestedPrice: 0,
  },
];

export function webSearchProvider(id: string | null | undefined): WebSearchProvider | undefined {
  return WEB_SEARCH_PROVIDERS.find((p) => p.id === (id || "").trim().toLowerCase());
}

export function webSearchProviderLabel(id: string): string {
  return webSearchProvider(id)?.label ?? id;
}

/** How model providers' keys start: one of these in a search key's place is a mix-up. */
const MODEL_KEY_PREFIXES = ["sk-ant-", "sk-or-", "sk-proj-", "sk-", "xai-", "gsk_", "AIza"];
/** How search keys start: one of these in a model key's place is a mix-up. */
const SEARCH_KEY_PREFIXES = ["tvly-", "BSA"];

/**
 * A warning when the key typed into a web search connection looks like it belongs to
 * another service: a model provider's key, or another search service's. Empty when
 * nothing looks wrong.
 */
export function searchKeyWarning(providerId: string, rawKey: string): string {
  const key = rawKey.trim();
  const provider = webSearchProvider(providerId);
  if (!key || !provider || !provider.needsKey) return "";
  if (provider.keyPrefix && key.startsWith(provider.keyPrefix)) return "";
  const other = WEB_SEARCH_PROVIDERS.find((p) => p.keyPrefix && p.id !== provider.id && key.startsWith(p.keyPrefix));
  if (other) return `This looks like a ${other.label} key, not a ${provider.label} one.`;
  if (MODEL_KEY_PREFIXES.some((prefix) => key.startsWith(prefix))) {
    return "This looks like a model provider's API key (OpenAI, Anthropic, OpenRouter…), not a web search key. Add it under Model providers instead.";
  }
  if (provider.keyPrefix) {
    return `${provider.label} keys usually start with ${provider.keyPrefix}. Check that this is the right key.`;
  }
  return "";
}

/** A warning when the key typed into a model connection looks like a web search key. */
export function modelKeyWarning(rawKey: string): string {
  const key = rawKey.trim();
  const search = SEARCH_KEY_PREFIXES.find((prefix) => key.startsWith(prefix));
  if (!search) return "";
  const provider = WEB_SEARCH_PROVIDERS.find((p) => p.keyPrefix === search);
  return `This looks like a ${provider?.label ?? "web search"} key, not a model provider's. Add it under Web search instead.`;
}
