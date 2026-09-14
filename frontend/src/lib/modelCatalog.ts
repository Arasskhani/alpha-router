export type ModelKind =
  | "text"
  | "image"
  | "embeddings"
  | "audio"
  | "video"
  | "rerank"
  | "speech"
  | "transcription";

export type ModelAccessType = "public" | "private";

export type CodeInterpreterCompatibilityInfo = {
  status: "compatible" | "unknown" | "probing" | "degraded" | "incompatible";
  compatible: boolean;
  selectable: boolean;
  auto_router?: boolean;
  verified?: boolean;
  score?: number | null;
  reason_code?: string | null;
  reason_detail?: string | null;
  manual_override?: string | null;
};

export type CatalogModel = {
  id: number;
  external_id: string;
  display_name?: string | null;
  enabled: boolean;
  /** Sticky admin lock — sync / connection enable will not clear until admin turns ON. */
  admin_disabled?: boolean;
  /** Admin system default for users who have not chosen a personal default. */
  is_system_default?: boolean;
  /** Kinds this model is the system default for (e.g. "text", "transcription", "image"). */
  default_kinds?: string[];
  access_type?: ModelAccessType;
  assignment_counts?: { users: number; groups: number };
  input_cost_per_1k: number | null;
  output_cost_per_1k: number | null;
  total_cost_per_1k: number;
  kinds?: ModelKind[];
  is_image_model?: boolean;
  is_video_model?: boolean;
  supports_text_to_video?: boolean;
  supports_image_to_video?: boolean;
  title?: string;
  description?: string;
  context_length?: number | null;
  provider_author?: string;
  released_at?: string | null;
  /** First time this model was listed in Alpha Router. Null for pre-existing catalog rows. */
  first_seen_at?: string | null;
  code_interpreter?: CodeInterpreterCompatibilityInfo | null;
};

/** Short admin label for the measured Code Interpreter state. */
export function codeInterpreterLabel(m: CatalogModel): string {
  const info = m.code_interpreter;
  if (!info) return "Unknown";
  if (info.manual_override === "compatible") return "Allowed (pinned)";
  if (info.manual_override === "incompatible") return "Blocked (pinned)";
  switch (info.status) {
    case "compatible":
      return "Verified";
    case "degraded":
      return "Quarantined";
    case "incompatible":
      return "Blocked";
    case "probing":
      return "Probing";
    default:
      return "Unknown";
  }
}

export function codeInterpreterButtonClass(m: CatalogModel): string {
  const info = m.code_interpreter;
  if (!info) return "";
  if (info.status === "compatible") return " model-compat-btn--verified";
  if (info.status === "degraded" || info.status === "incompatible") {
    return " model-compat-btn--blocked";
  }
  return "";
}

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

export type ModelEnabledFilter = "on" | "off";
export type ModelAccessFilter = ModelAccessType;
export const MODEL_NEW_WINDOWS = [1, 3, 7, 14, 30] as const;
export type ModelNewFilter = (typeof MODEL_NEW_WINDOWS)[number];
export const MODEL_NEW_WINDOW_MS = 24 * 60 * 60 * 1000;

export function isNewlyListedModel(
  model: CatalogModel,
  days: ModelNewFilter,
  nowMs: number = Date.now(),
): boolean {
  if (!model.first_seen_at) return false;
  const seen = Date.parse(model.first_seen_at);
  if (Number.isNaN(seen)) return false;
  return seen >= nowMs - days * MODEL_NEW_WINDOW_MS;
}

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

export function enabledCounts(models: CatalogModel[]): Record<ModelEnabledFilter, number> {
  let on = 0;
  let off = 0;
  for (const m of models) {
    if (m.enabled) on += 1;
    else off += 1;
  }
  return { on, off };
}

export function accessCounts(models: CatalogModel[]): Record<ModelAccessFilter, number> {
  let pub = 0;
  let priv = 0;
  for (const m of models) {
    if ((m.access_type || "public") === "private") priv += 1;
    else pub += 1;
  }
  return { public: pub, private: priv };
}

export function newWindowCounts(
  models: CatalogModel[],
  nowMs: number = Date.now(),
): Record<ModelNewFilter, number> {
  const counts = Object.fromEntries(MODEL_NEW_WINDOWS.map((days) => [days, 0])) as Record<
    ModelNewFilter,
    number
  >;
  for (const days of MODEL_NEW_WINDOWS) {
    counts[days] = models.filter((m) => isNewlyListedModel(m, days, nowMs)).length;
  }
  return counts;
}

export function accessTypeLabel(m: CatalogModel): string {
  const access = m.access_type || "public";
  if (access !== "private") return "Public";
  const users = m.assignment_counts?.users ?? 0;
  const groups = m.assignment_counts?.groups ?? 0;
  const n = users + groups;
  return n > 0 ? `Private (${n})` : "Private";
}

export function filterCatalogModels(
  models: CatalogModel[],
  search: string,
  activeKind: ModelKind | null,
  enabledFilter: ModelEnabledFilter | null = null,
  accessFilter: ModelAccessFilter | null = null,
  newFilter: ModelNewFilter | null = null,
  nowMs: number = Date.now(),
): CatalogModel[] {
  const q = search.trim().toLowerCase();
  return models.filter((m) => {
    if (activeKind) {
      const kinds = m.kinds?.length ? m.kinds : (["text"] as ModelKind[]);
      if (!kinds.includes(activeKind)) return false;
    }
    if (enabledFilter === "on" && !m.enabled) return false;
    if (enabledFilter === "off" && m.enabled) return false;
    const access = m.access_type || "public";
    if (accessFilter && access !== accessFilter) return false;
    if (newFilter && !isNewlyListedModel(m, newFilter, nowMs)) return false;
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
