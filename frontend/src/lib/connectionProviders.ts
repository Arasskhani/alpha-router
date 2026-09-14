/** Built-in provider catalog for connection autocomplete (no live web lookup). */

export type ConnectionProviderPreset = {
  /** Canonical provider_type stored on the connection. */
  id: string;
  /** Human label shown in suggestions. */
  label: string;
  /** Default OpenAI-compatible or vendor API root. */
  baseUrl: string;
  /** Extra search aliases (lowercase). */
  aliases?: string[];
};

const CONNECTION_PROVIDER_PRESETS: readonly ConnectionProviderPreset[] = [
  {
    id: "openrouter",
    label: "OpenRouter",
    baseUrl: "https://openrouter.ai/api/v1",
    aliases: ["open router"],
  },
  {
    id: "openai",
    label: "OpenAI",
    baseUrl: "https://api.openai.com/v1",
    aliases: ["chatgpt", "gpt"],
  },
  {
    id: "anthropic",
    label: "Anthropic",
    baseUrl: "https://api.anthropic.com/v1",
    aliases: ["claude"],
  },
  {
    id: "google",
    label: "Google Gemini",
    baseUrl: "https://generativelanguage.googleapis.com/v1beta",
    aliases: ["gemini", "google ai", "googleai"],
  },
  {
    id: "xai",
    label: "xAI",
    baseUrl: "https://api.x.ai/v1",
    aliases: ["grok", "x.ai"],
  },
  {
    id: "deepseek",
    label: "DeepSeek",
    baseUrl: "https://api.deepseek.com/v1",
  },
  {
    id: "mistral",
    label: "Mistral",
    baseUrl: "https://api.mistral.ai/v1",
    aliases: ["mistralai"],
  },
  {
    id: "groq",
    label: "Groq",
    baseUrl: "https://api.groq.com/openai/v1",
  },
  {
    id: "together",
    label: "Together AI",
    baseUrl: "https://api.together.xyz/v1",
    aliases: ["togetherai", "together.ai"],
  },
  {
    id: "fireworks",
    label: "Fireworks",
    baseUrl: "https://api.fireworks.ai/inference/v1",
    aliases: ["fireworks.ai"],
  },
  {
    id: "perplexity",
    label: "Perplexity",
    baseUrl: "https://api.perplexity.ai",
  },
  {
    id: "cohere",
    label: "Cohere",
    baseUrl: "https://api.cohere.ai/v2",
  },
  {
    id: "azure",
    label: "Azure OpenAI",
    baseUrl: "https://YOUR_RESOURCE.openai.azure.com/openai/v1",
    aliases: ["azure openai", "aoai"],
  },
  {
    id: "ollama",
    label: "Ollama",
    baseUrl: "http://127.0.0.1:11434/v1",
  },
  {
    id: "lmstudio",
    label: "LM Studio",
    baseUrl: "http://127.0.0.1:1234/v1",
    aliases: ["lm studio", "lm-studio"],
  },
  {
    id: "custom",
    label: "Custom (OpenAI-compatible)",
    baseUrl: "",
    aliases: ["openai-compatible", "compatible"],
  },
] as const;

function normalizeQuery(value: string): string {
  return value.trim().toLowerCase().replace(/\s+/g, " ");
}

function presetMatches(preset: ConnectionProviderPreset, query: string): boolean {
  if (!query) return true;
  if (preset.id.includes(query)) return true;
  if (preset.label.toLowerCase().includes(query)) return true;
  return (preset.aliases ?? []).some((alias) => alias.includes(query) || query.includes(alias));
}

/** Ranked suggestions for the provider autocomplete panel. */
export function suggestConnectionProviders(query: string, limit = 8): ConnectionProviderPreset[] {
  const q = normalizeQuery(query);
  const scored = CONNECTION_PROVIDER_PRESETS.map((preset) => {
    if (!presetMatches(preset, q)) return null;
    let score = 0;
    if (!q) score = 1;
    else if (preset.id === q) score = 100;
    else if ((preset.aliases ?? []).includes(q)) score = 95;
    else if (preset.id.startsWith(q)) score = 80;
    else if (preset.label.toLowerCase().startsWith(q)) score = 70;
    else if (preset.id.includes(q)) score = 50;
    else score = 20;
    return { preset, score };
  }).filter((row): row is { preset: ConnectionProviderPreset; score: number } => row !== null);

  scored.sort((a, b) => b.score - a.score || a.preset.label.localeCompare(b.preset.label));
  return scored.slice(0, limit).map((row) => row.preset);
}

/** Exact / alias match used to autofill provider id + base URL. */
export function resolveConnectionProvider(query: string): ConnectionProviderPreset | null {
  const q = normalizeQuery(query);
  if (!q) return null;
  const exact = CONNECTION_PROVIDER_PRESETS.find(
    (preset) =>
      preset.id === q ||
      preset.label.toLowerCase() === q ||
      (preset.aliases ?? []).includes(q),
  );
  return exact ?? null;
}

export function knownConnectionBaseUrls(): Set<string> {
  return new Set(
    CONNECTION_PROVIDER_PRESETS.map((preset) => preset.baseUrl.trim()).filter(Boolean),
  );
}
