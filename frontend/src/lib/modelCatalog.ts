export type ModelKind =
  | "text"
  | "image"
  | "embeddings"
  | "audio"
  | "video"
  | "rerank"
  | "speech"
  | "transcription";

export type CatalogModel = {
  id: number;
  external_id: string;
  display_name?: string | null;
  enabled: boolean;
  input_cost_per_1k: number | null;
  output_cost_per_1k: number | null;
  total_cost_per_1k: number;
  kinds?: ModelKind[];
  is_image_model?: boolean;
  title?: string;
  description?: string;
  context_length?: number | null;
  provider_author?: string;
  released_at?: string | null;
};

export const MODEL_KIND_ORDER: ModelKind[] = [
  "text",
  "image",
  "embeddings",
  "audio",
  "video",
  "rerank",
  "speech",
  "transcription",
];

export const MODEL_KIND_LABELS: Record<ModelKind, string> = {
  text: "Text",
  image: "Image",
  embeddings: "Embeddings",
  audio: "Audio",
  video: "Video",
  rerank: "Rerank",
  speech: "Speech",
  transcription: "Transcription",
};

export function kindCounts(models: CatalogModel[]): Record<ModelKind, number> {
  const counts = Object.fromEntries(MODEL_KIND_ORDER.map((k) => [k, 0])) as Record<ModelKind, number>;
  for (const m of models) {
    const kinds = m.kinds?.length ? m.kinds : (["text"] as ModelKind[]);
    for (const k of kinds) {
      if (k in counts) counts[k] += 1;
    }
  }
  return counts;
}

export function filterCatalogModels(
  models: CatalogModel[],
  search: string,
  activeKind: ModelKind | null,
): CatalogModel[] {
  const q = search.trim().toLowerCase();
  return models.filter((m) => {
    if (activeKind) {
      const kinds = m.kinds?.length ? m.kinds : (["text"] as ModelKind[]);
      if (!kinds.includes(activeKind)) return false;
    }
    if (!q) return true;
    const name = (m.display_name || m.title || "").toLowerCase();
    const desc = (m.description || "").toLowerCase();
    return (
      m.external_id.toLowerCase().includes(q) ||
      name.includes(q) ||
      desc.includes(q)
    );
  });
}
