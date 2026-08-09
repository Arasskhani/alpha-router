import ai21 from "@lobehub/icons-static-svg/icons/ai21-brand-color.svg?url";
import alibaba from "@lobehub/icons-static-svg/icons/alibaba-color.svg?url";
import amazon from "@lobehub/icons-static-svg/icons/bedrock-color.svg?url";
import anthropic from "@lobehub/icons-static-svg/icons/claude-color.svg?url";
import cohere from "@lobehub/icons-static-svg/icons/cohere-color.svg?url";
import deepseek from "@lobehub/icons-static-svg/icons/deepseek-color.svg?url";
import gemini from "@lobehub/icons-static-svg/icons/gemini-color.svg?url";
import google from "@lobehub/icons-static-svg/icons/google-color.svg?url";
import groq from "@lobehub/icons-static-svg/icons/groq.svg?url";
import meta from "@lobehub/icons-static-svg/icons/meta-color.svg?url";
import microsoft from "@lobehub/icons-static-svg/icons/microsoft-color.svg?url";
import mistral from "@lobehub/icons-static-svg/icons/mistral-color.svg?url";
import moonshot from "@lobehub/icons-static-svg/icons/moonshot.svg?url";
import nvidia from "@lobehub/icons-static-svg/icons/nvidia-color.svg?url";
import openai from "@lobehub/icons-static-svg/icons/openai.svg?url";
import openrouter from "@lobehub/icons-static-svg/icons/openrouter-color.svg?url";
import perplexity from "@lobehub/icons-static-svg/icons/perplexity-color.svg?url";
import qwen from "@lobehub/icons-static-svg/icons/qwen-color.svg?url";
import xai from "@lobehub/icons-static-svg/icons/xai.svg?url";
import zhipu from "@lobehub/icons-static-svg/icons/zhipu-color.svg?url";
import { resolveProviderIconSlug } from "../lib/modelProvider";

// Runway is present in OpenRouter's catalog but is not included in the
// installed LobeHub icon set. Keep a small local mark so new Runway models do
// not fall back to the generic unknown-provider icon.
const runway =
  "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'%3E%3Crect width='24' height='24' rx='5' fill='%23000'/%3E%3Cpath fill='%23fff' d='M6 5h6.1c3.8 0 5.9 1.8 5.9 4.7 0 2.1-1.1 3.6-3.1 4.3L18.5 19h-3.8l-3.1-4.4H9.4V19H6V5Zm3.4 2.9v3.8h2.5c1.8 0 2.7-.6 2.7-1.9 0-1.3-.9-1.9-2.7-1.9H9.4Z'/%3E%3C/svg%3E";

type Props = {
  /** Full model id (`google/gemini-…`) or bare provider slug. */
  modelId?: string | null;
  provider?: string | null;
  size?: number;
  className?: string;
  title?: string;
};

/** Prefer *-color brand marks from @lobehub/icons-static-svg (MIT). */
const LOGO_BY_SLUG: Record<string, string> = {
  ai21,
  alibaba,
  amazon,
  anthropic,
  bedrock: amazon,
  claude: anthropic,
  cohere,
  deepseek,
  gemini,
  google,
  groq,
  meta,
  microsoft,
  mistral,
  moonshot,
  nvidia,
  openai,
  openrouter,
  perplexity,
  qwen,
  runway,
  xai,
  grok: xai,
  zhipu,
};

function logoForSlug(slug: string): string | null {
  if (LOGO_BY_SLUG[slug]) return LOGO_BY_SLUG[slug]!;
  // Qwen models often resolve as alibaba — already mapped; also accept qwen slug.
  if (slug === "qwen") return qwen;
  return null;
}

/**
 * Provider brand mark next to model names.
 * Uses colored official/near-official SVGs via <img> (preserves gradients, no ID clashes).
 */
export default function ModelProviderIcon({
  modelId,
  provider,
  size = 16,
  className = "",
  title,
}: Props) {
  const slug = resolveProviderIconSlug(modelId, provider);
  const src = logoForSlug(slug);
  const label = title || slug;

  if (!src) {
    return (
      <span
        className={`model-provider-icon model-provider-icon--fallback${className ? ` ${className}` : ""}`}
        style={{ width: size, height: size }}
        title={label}
        aria-hidden
      >
        <svg viewBox="0 0 24 24" width={size} height={size} focusable="false">
          <circle cx="12" cy="12" r="9" fill="#94a3b8" />
          <text x="12" y="16" fill="#fff" textAnchor="middle" fontSize="10" fontWeight="700">
            {slug === "unknown" ? "?" : slug.slice(0, 2).toUpperCase()}
          </text>
        </svg>
      </span>
    );
  }

  return (
    <span
      className={`model-provider-icon${className ? ` ${className}` : ""}`}
      style={{ width: size, height: size }}
      title={label}
      aria-hidden
    >
      <img src={src} alt="" width={size} height={size} draggable={false} />
    </span>
  );
}
