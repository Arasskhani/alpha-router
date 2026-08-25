/** Best-known dense size for a catalog embedding model id.
 * Keep in sync with `suggested_embedding_dimensions` in knowledge_embedding_service.py.
 */
export function suggestedEmbeddingDimensions(externalId: string): number {
  const lowered = (externalId || "").toLowerCase();
  if (lowered.includes("text-embedding-3-large")) return 3072;
  if (lowered.includes("text-embedding-3-small") || lowered.includes("ada-002")) return 1536;
  if (lowered.includes("gemini-embedding")) return 3072;
  if (lowered.includes("qwen3-embedding-8b")) return 4096;
  if (lowered.includes("qwen3-embedding")) return 2560;
  if (lowered.includes("mistral-embed") || lowered.includes("codestral-embed")) return 1024;
  return 1536;
}

export function embeddingModelOptionLabel(
  externalId: string,
  provider: string,
  dimensions = suggestedEmbeddingDimensions(externalId),
): string {
  return `${externalId} · ${provider} · ${dimensions}d`;
}

export function embeddingModelIdFromSpec(spec: string): string {
  const raw = (spec || "").trim();
  const idx = raw.indexOf(":");
  return idx >= 0 ? raw.slice(idx + 1) : raw;
}
