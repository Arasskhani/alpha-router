/** Derive upstream provider / brand slug from a model id / key / label. */

const ALIASES: Record<string, string> = {
  "openai-compatible": "openai",
  "google-ai-studio": "google",
  "google-gemini": "gemini",
  gemini: "gemini",
  "meta-llama": "meta",
  llama: "meta",
  mistralai: "mistral",
  "x-ai": "xai",
  grok: "xai",
  "amazon-bedrock": "amazon",
  bedrock: "amazon",
  azure: "microsoft",
  "azure-openai": "microsoft",
  azureai: "microsoft",
  moonshotai: "moonshot",
  "z-ai": "zhipu",
  zhipuai: "zhipu",
  qwen: "alibaba",
  "alibaba-cloud": "alibaba",
  alibabacloud: "alibaba",
  dashscope: "alibaba",
  claude: "anthropic",
};

/**
 * Resolve the brand slug used for logos.
 * Prefer model-id specifics (e.g. Gemini sparkle) over a coarse provider label.
 */
export function providerFromModelId(modelId: string | null | undefined): string {
  const raw = (modelId || "").trim().toLowerCase();
  if (!raw) return "unknown";

  // Brand-specific tokens take priority over author prefix.
  if (raw.includes("gemini")) return "gemini";
  if (raw.includes("claude")) return "anthropic";
  if (raw.includes("grok")) return "xai";
  if (raw.includes("deepseek")) return "deepseek";
  if (raw.includes("qwen")) return "qwen";
  if (raw.includes("mistral") || raw.includes("mixtral")) return "mistral";
  if (raw.includes("llama")) return "meta";
  if (raw.includes("gpt") || /(^|\/)o[1-4]/.test(raw)) return "openai";

  let slug = raw.includes("/") ? raw.split("/", 1)[0]! : raw;
  slug = ALIASES[slug] || slug;
  return slug || "unknown";
}

/** Merge explicit provider label with model-id brand detection. */
export function resolveProviderIconSlug(
  modelId: string | null | undefined,
  provider?: string | null,
): string {
  const fromId = providerFromModelId(modelId);
  // Keep specific brands from the model id even when provider="google".
  if (
    fromId === "gemini" ||
    fromId === "anthropic" ||
    fromId === "xai" ||
    fromId === "openai" ||
    fromId === "meta" ||
    fromId === "mistral" ||
    fromId === "deepseek" ||
    fromId === "qwen" ||
    fromId === "alibaba"
  ) {
    return fromId;
  }
  const rawProvider = (provider || "").trim().toLowerCase();
  if (rawProvider) {
    if (rawProvider.includes("gemini")) return "gemini";
    return ALIASES[rawProvider] || rawProvider;
  }
  return fromId;
}
