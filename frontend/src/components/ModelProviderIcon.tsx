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
          <path
            fill="#fff"
            d="M12 7.2a1.2 1.2 0 110 2.4 1.2 1.2 0 010-2.4zm-1.1 4.3h2.2v5.3h-2.2v-5.3z"
          />
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
