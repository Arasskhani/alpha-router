/** Image aspect-ratio presets — aligned with OpenRouter `image_config.aspect_ratio`. */

export type ImageAspectPresetId = "square" | "wide" | "tall" | "landscape" | "portrait" | "custom";

export type ImageAspectPreset = {
  id: ImageAspectPresetId;
  label: string;
  shortLabel: string;
  aspectRatio: string;
};

export const DEFAULT_IMAGE_ASPECT_PRESET: ImageAspectPresetId = "square";
export const DEFAULT_CUSTOM_ASPECT_RATIO = "16:9";

/** OpenRouter-supported aspect ratio labels. */
export const SUPPORTED_ASPECT_RATIOS = [
  "1:1",
  "2:3",
  "3:2",
  "3:4",
  "4:3",
  "4:5",
  "5:4",
  "9:16",
  "16:9",
  "21:9",
] as const;

export type SupportedAspectRatio = (typeof SUPPORTED_ASPECT_RATIOS)[number];

export const IMAGE_ASPECT_PRESETS: ImageAspectPreset[] = [
  { id: "square", label: "Square", shortLabel: "1:1", aspectRatio: "1:1" },
  { id: "wide", label: "Wide", shortLabel: "16:9", aspectRatio: "16:9" },
  { id: "tall", label: "Tall", shortLabel: "9:16", aspectRatio: "9:16" },
  { id: "landscape", label: "Landscape", shortLabel: "3:2", aspectRatio: "3:2" },
  { id: "portrait", label: "Portrait", shortLabel: "2:3", aspectRatio: "2:3" },
];

/** @deprecated Use IMAGE_ASPECT_PRESETS */
export const IMAGE_SIZE_PRESETS = IMAGE_ASPECT_PRESETS;

const PRESET_BY_ID = Object.fromEntries(
  IMAGE_ASPECT_PRESETS.map((p) => [p.id, p]),
) as Record<Exclude<ImageAspectPresetId, "custom">, ImageAspectPreset>;

const ASPECT_RATIO_TO_PRESET: Record<string, ImageAspectPresetId> = {
  "1:1": "square",
  "16:9": "wide",
  "9:16": "tall",
  "3:2": "landscape",
  "2:3": "portrait",
};

/** Default WxH per aspect ratio for providers that still require `size`. */
const ASPECT_RATIO_TO_DEFAULT_SIZE: Record<string, string> = {
  "1:1": "1024x1024",
  "16:9": "1344x768",
  "9:16": "768x1344",
  "3:2": "1248x832",
  "2:3": "832x1248",
  "4:3": "1184x888",
  "3:4": "888x1184",
  "4:5": "896x1120",
  "5:4": "1120x896",
  "21:9": "1536x656",
};

const ASPECT_PATTERN = /^(\d+)\s*:\s*(\d+)$/i;
const LEGACY_SIZE_PATTERN = /^(\d+)\s*x\s*(\d+)$/i;

function gcd(a: number, b: number): number {
  let x = Math.abs(a);
  let y = Math.abs(b);
  while (y !== 0) {
    const t = y;
    y = x % y;
    x = t;
  }
  return x || 1;
}

function snapAspectRatio(w: number, h: number): SupportedAspectRatio {
  const ratio = w / h;
  let best: SupportedAspectRatio = "1:1";
  let bestDiff = Number.POSITIVE_INFINITY;
  for (const label of SUPPORTED_ASPECT_RATIOS) {
    const [a, b] = label.split(":").map((n) => parseInt(n, 10));
    const diff = Math.abs(ratio - a / b);
    if (diff < bestDiff) {
      bestDiff = diff;
      best = label;
    }
  }
  return best;
}

export function normalizeCustomAspectRatio(raw?: string | null): string | null {
  if (!raw) return null;
  const trimmed = raw.trim().replace(/\s+/g, "");
  const match = trimmed.match(ASPECT_PATTERN);
  if (!match) return null;
  const w = parseInt(match[1], 10);
  const h = parseInt(match[2], 10);
  if (!Number.isFinite(w) || !Number.isFinite(h) || w <= 0 || h <= 0) return null;
  const simplified = `${w / gcd(w, h)}:${h / gcd(w, h)}`;
  if ((SUPPORTED_ASPECT_RATIOS as readonly string[]).includes(simplified)) {
    return simplified;
  }
  return snapAspectRatio(w, h);
}

/** Migrate legacy WxH session values (e.g. 1280x720) to aspect ratio. */
export function aspectRatioFromLegacySize(size?: string | null): string | null {
  if (!size) return null;
  const match = size.trim().replace(/\s+/g, "").match(LEGACY_SIZE_PATTERN);
  if (!match) return null;
  const w = parseInt(match[1], 10);
  const h = parseInt(match[2], 10);
  if (!Number.isFinite(w) || !Number.isFinite(h) || w <= 0 || h <= 0) return null;
  return snapAspectRatio(w, h);
}

export function normalizeImageAspectPreset(raw?: string | null): ImageAspectPresetId {
  if (raw === "custom") return "custom";
  if (raw && raw in PRESET_BY_ID) return raw as ImageAspectPresetId;
  return DEFAULT_IMAGE_ASPECT_PRESET;
}

export function aspectRatioFromPreset(
  preset: ImageAspectPresetId,
  customAspect?: string,
): string {
  if (preset === "custom") {
    return normalizeCustomAspectRatio(customAspect) ?? DEFAULT_CUSTOM_ASPECT_RATIO;
  }
  return PRESET_BY_ID[preset].aspectRatio;
}

export function presetFromAspectRatio(aspectRatio?: string | null): ImageAspectPresetId | undefined {
  if (!aspectRatio) return undefined;
  const normalized = normalizeCustomAspectRatio(aspectRatio);
  if (!normalized) return undefined;
  return ASPECT_RATIO_TO_PRESET[normalized] ?? "custom";
}

export function aspectLabelForPreset(preset: ImageAspectPresetId, customAspect?: string): string {
  if (preset === "custom") {
    return normalizeCustomAspectRatio(customAspect) ?? DEFAULT_CUSTOM_ASPECT_RATIO;
  }
  return PRESET_BY_ID[preset].shortLabel;
}

export function defaultSizeForAspectRatio(aspectRatio: string): string {
  const normalized = normalizeCustomAspectRatio(aspectRatio) ?? aspectRatio;
  return ASPECT_RATIO_TO_DEFAULT_SIZE[normalized] ?? "1024x1024";
}

export function resolveSessionAspectRatio(tools: {
  imageAspectRatio: ImageAspectPresetId;
  imageCustomAspectRatio?: string;
  /** @deprecated legacy WxH field */
  imageCustomSize?: string;
}): { aspectRatio: string; preset: ImageAspectPresetId } {
  const preset = normalizeImageAspectPreset(tools.imageAspectRatio);
  if (preset === "custom") {
    const fromCustom =
      normalizeCustomAspectRatio(tools.imageCustomAspectRatio) ??
      aspectRatioFromLegacySize(tools.imageCustomSize);
    const aspectRatio = fromCustom ?? DEFAULT_CUSTOM_ASPECT_RATIO;
    return { aspectRatio, preset: "custom" };
  }
  return { aspectRatio: PRESET_BY_ID[preset].aspectRatio, preset };
}

function applyAspectToken(token: string, found: { preset?: ImageAspectPresetId; aspectRatio?: string }) {
  const normalized = normalizeCustomAspectRatio(token.replace(/\s+/g, ""));
  if (normalized) {
    found.aspectRatio = normalized;
    found.preset = ASPECT_RATIO_TO_PRESET[normalized] ?? "custom";
    return;
  }
  const legacySize = token.replace(/\s+/g, "").match(LEGACY_SIZE_PATTERN);
  if (legacySize) {
    const w = parseInt(legacySize[1], 10);
    const h = parseInt(legacySize[2], 10);
    if (w > 0 && h > 0) {
      const ar = snapAspectRatio(w, h);
      found.aspectRatio = ar;
      found.preset = ASPECT_RATIO_TO_PRESET[ar] ?? "custom";
    }
  }
}

/** Parse explicit aspect hints from prompt; strip matched tokens from cleaned prompt. */
export function parseAspectRatioFromPrompt(prompt: string): {
  cleanedPrompt: string;
  preset?: ImageAspectPresetId;
  aspectRatio?: string;
} {
  let text = prompt.trim();
  const found: { preset?: ImageAspectPresetId; aspectRatio?: string } = {};

  text = text.replace(
    /--(?:ar|aspect(?:-ratio)?)\s*[:=]?\s*(\d+\s*:\s*\d+|\d+\s*x\s*\d+)/gi,
    (_, token: string) => {
      if (!found.aspectRatio) applyAspectToken(token, found);
      return " ";
    },
  );

  if (!found.aspectRatio) {
    text = text.replace(/\b(16:9|9:16|1:1|3:2|2:3|4:3|3:4|21:9)\b/g, (match) => {
      if (!found.aspectRatio) applyAspectToken(match, found);
      return " ";
    });
  }

  const cleanedPrompt = text.replace(/\s{2,}/g, " ").trim();
  return { cleanedPrompt, ...found };
}

export type ResolvedImageGeneration = {
  prompt: string;
  aspectRatio: string;
  preset: ImageAspectPresetId;
  /** When img2img, backend derives size from source; omit aspect override. */
  useSourceDimensions: boolean;
};

export function resolveImageGeneration(opts: {
  prompt: string;
  sessionPreset: ImageAspectPresetId;
  sessionCustomAspect?: string;
  /** @deprecated */
  sessionCustomSize?: string;
  hasReference: boolean;
}): ResolvedImageGeneration {
  if (opts.hasReference) {
    return {
      prompt: opts.prompt.trim(),
      aspectRatio: "",
      preset: opts.sessionPreset,
      useSourceDimensions: true,
    };
  }

  const session = resolveSessionAspectRatio({
    imageAspectRatio: opts.sessionPreset,
    imageCustomAspectRatio: opts.sessionCustomAspect,
    imageCustomSize: opts.sessionCustomSize,
  });
  const parsed = parseAspectRatioFromPrompt(opts.prompt);
  const preset = parsed.preset ?? session.preset;
  const aspectRatio = parsed.aspectRatio ?? session.aspectRatio;
  const cleaned = parsed.cleanedPrompt;
  const prompt = cleaned || (parsed.aspectRatio ? "Generate image" : opts.prompt.trim());
  return {
    prompt,
    aspectRatio,
    preset,
    useSourceDimensions: false,
  };
}

export function resolveRegenerateImageGeneration(opts: {
  prompt: string;
  payloadAspectRatio?: string;
  payloadPreset?: ImageAspectPresetId;
  /** @deprecated stored WxH from older messages */
  payloadSize?: string;
  sessionPreset: ImageAspectPresetId;
  sessionCustomAspect?: string;
  sessionCustomSize?: string;
  hasReference: boolean;
}): ResolvedImageGeneration {
  if (opts.hasReference) {
    return resolveImageGeneration({
      prompt: opts.prompt,
      sessionPreset: opts.sessionPreset,
      sessionCustomAspect: opts.sessionCustomAspect,
      sessionCustomSize: opts.sessionCustomSize,
      hasReference: true,
    });
  }

  const fromPayloadRatio =
    opts.payloadAspectRatio ??
    (opts.payloadSize ? aspectRatioFromLegacySize(opts.payloadSize) : undefined);
  const fromPayload =
    opts.payloadPreset ?? (fromPayloadRatio ? presetFromAspectRatio(fromPayloadRatio) : undefined);

  if (fromPayload && fromPayloadRatio) {
    return {
      prompt: opts.prompt.trim(),
      aspectRatio: normalizeCustomAspectRatio(fromPayloadRatio) ?? fromPayloadRatio,
      preset: fromPayload,
      useSourceDimensions: false,
    };
  }

  return resolveImageGeneration({
    prompt: opts.prompt,
    sessionPreset: opts.sessionPreset,
    sessionCustomAspect: opts.sessionCustomAspect,
    sessionCustomSize: opts.sessionCustomSize,
    hasReference: false,
  });
}

/** Read pixel dimensions from a data URL or same-origin/http(s) image URL. */
export function readReferenceImageDimensions(
  referenceUrl: string,
): Promise<{ width: number; height: number } | null> {
  const ref = referenceUrl.trim();
  if (!ref) return Promise.resolve(null);

  return new Promise((resolve) => {
    const img = new Image();
    img.onload = () => {
      const w = img.naturalWidth;
      const h = img.naturalHeight;
      resolve(w > 0 && h > 0 ? { width: w, height: h } : null);
    };
    img.onerror = () => resolve(null);
    if (ref.startsWith("data:") || ref.startsWith("blob:")) {
      img.src = ref;
      return;
    }
    if (ref.startsWith("http://") || ref.startsWith("https://") || ref.startsWith("/")) {
      img.crossOrigin = "anonymous";
      img.src = ref;
      return;
    }
    resolve(null);
  });
}
