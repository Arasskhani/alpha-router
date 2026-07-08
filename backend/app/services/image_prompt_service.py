"""Enhance / translate user prompts via a lightweight model call."""

import re

from litellm import acompletion
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.language_detect import detect_prompt_language
from app.models.user import User
from app.services.budget_service import budget_request_blocked, get_user_budget_state
from app.services.proxy_service import (
    _apply_litellm_provider_kwargs,
    _litellm_model_for_provider,
    resolve_model_and_key,
)

ENHANCE_MODES = ("improve", "translate", "translate_improve")
ENHANCE_CONTEXTS = ("image", "chat")

# Legacy aliases kept for older clients.
_MODE_ALIASES = {
    "professional": "improve",
    "translate_professional": "translate_improve",
}

_IMAGE_IMPROVE_SYSTEM = (
    "You make MINIMAL edits to image-generation prompts. Your job is a light polish, "
    "NOT a rewrite.\n\n"
    "Rules:\n"
    "- Keep the SAME language as the input.\n"
    "- Preserve the user's exact subject, scene, style, mood, and wording order.\n"
    "- Only fix grammar and clarify vague phrases (e.g. 'good lighting' -> 'soft natural lighting').\n"
    "- Do NOT add new subjects, objects, people, places, colors, camera angles, or art styles.\n"
    "- Do NOT add quality buzzwords (8K, photorealistic, masterpiece) unless the user used them.\n"
    "- If the prompt is already clear, return it UNCHANGED.\n"
    "- Output may be at most slightly longer (~30%).\n\n"
    "Example:\n"
    "Input: یک گربه نارنجی روی مبل قهوه‌ای\n"
    "Good output: یک گربه نارنجی روی مبل قهوه‌ای\n"
    "Bad output: یک گربه پشمالوی نارنجی روی مبل چرمی قدیمی در نور غروب با کیفیت سینمایی...\n\n"
    "Return ONLY the improved prompt with no quotes, preamble, or explanation."
)

_CHAT_IMPROVE_SYSTEM = (
    "You make MINIMAL edits to user messages for a chat assistant. Your job is a light polish, "
    "NOT a rewrite.\n\n"
    "Rules:\n"
    "- Keep the SAME language as the input.\n"
    "- Preserve the user's exact question, request, topics, tone, and wording order.\n"
    "- Only fix grammar, spelling, and clarify vague phrases.\n"
    "- Do NOT add new questions, constraints, background, or details the user did not mention.\n"
    "- Do NOT turn the message into an image-generation prompt or add visual/scene details.\n"
    "- If the message is already clear, return it UNCHANGED.\n"
    "- Output may be at most slightly longer (~30%).\n\n"
    "Return ONLY the improved message with no quotes, preamble, or explanation."
)

_IMAGE_TRANSLATE_SYSTEM = (
    "You translate image-generation prompts into fluent natural English. "
    "Translate faithfully without adding new details or changing the meaning. "
    "Return ONLY the translated prompt with no quotes, no preamble, and no explanation."
)

_CHAT_TRANSLATE_SYSTEM = (
    "You translate user messages for a chat assistant into fluent natural English. "
    "Translate faithfully without adding new details or changing the meaning. "
    "Return ONLY the translated message with no quotes, no preamble, and no explanation."
)

_IMAGE_TRANSLATE_IMPROVE_SYSTEM = (
    "You translate image-generation prompts into fluent natural English, then make MINIMAL "
    "edits to the translation. Clarify vague wording and fix grammar while preserving the "
    "user's exact subject, scene, style, mood, and intent. Do NOT add new subjects, objects, "
    "locations, characters, colors, camera angles, or art styles the user did not mention. "
    "Do NOT rewrite from scratch. Do NOT add quality buzzwords unless the user used them. "
    "If already clear after translation, return nearly unchanged. "
    "The output MUST be in English and may be at most ~30% longer than a faithful translation. "
    "Return ONLY the result with no quotes, no preamble, and no explanation."
)

_CHAT_TRANSLATE_IMPROVE_SYSTEM = (
    "You translate user messages for a chat assistant into fluent natural English, then make "
    "MINIMAL edits to the translation. Clarify vague wording and fix grammar while preserving "
    "the user's exact question, request, topics, tone, and intent. Do NOT add new questions, "
    "constraints, or details the user did not mention. Do NOT turn the message into an "
    "image-generation prompt. If already clear after translation, return nearly unchanged. "
    "The output MUST be in English and may be at most ~30% longer than a faithful translation. "
    "Return ONLY the result with no quotes, no preamble, and no explanation."
)

_SYSTEM_BY_CONTEXT_AND_MODE: dict[str, dict[str, str]] = {
    "image": {
        "improve": _IMAGE_IMPROVE_SYSTEM,
        "translate": _IMAGE_TRANSLATE_SYSTEM,
        "translate_improve": _IMAGE_TRANSLATE_IMPROVE_SYSTEM,
    },
    "chat": {
        "improve": _CHAT_IMPROVE_SYSTEM,
        "translate": _CHAT_TRANSLATE_SYSTEM,
        "translate_improve": _CHAT_TRANSLATE_IMPROVE_SYSTEM,
    },
}

_WORD_RE = re.compile(r"[\w\u0600-\u06FF]+", re.UNICODE)

_IMPROVE_MAX_LENGTH_RATIO = 1.35
_IMPROVE_MIN_JACCARD = 0.45
_IMPROVE_MAX_NOVEL_WORD_RATIO = 0.4
_TRANSLATE_IMPROVE_MAX_LENGTH_RATIO = 1.8


def _normalize_mode(mode: str) -> str | None:
    key = (mode or "").strip()
    key = _MODE_ALIASES.get(key, key)
    return key if key in ENHANCE_MODES else None


def _normalize_context(context: str) -> str:
    key = (context or "").strip().lower()
    return key if key in ENHANCE_CONTEXTS else "image"


def _tokenize(text: str) -> set[str]:
    return {w.lower() for w in _WORD_RE.findall(text) if len(w) > 1}


def _jaccard_similarity(a: str, b: str) -> float:
    tokens_a = _tokenize(a)
    tokens_b = _tokenize(b)
    if not tokens_a and not tokens_b:
        return 1.0
    if not tokens_a or not tokens_b:
        return 0.0
    intersection = len(tokens_a & tokens_b)
    union = len(tokens_a | tokens_b)
    return intersection / union if union else 0.0


def _novel_word_ratio(result: str, original: str) -> float:
    original_tokens = _tokenize(original)
    result_tokens = _tokenize(result)
    if not result_tokens:
        return 0.0
    novel = result_tokens - original_tokens
    return len(novel) / len(result_tokens)


def _sanitize_prompt(raw: str, fallback: str) -> str:
    t = (raw or "").strip().strip("\"'“”‘’")
    t = re.sub(r"\s+\n", "\n", t).strip()
    if not t:
        return fallback
    return t if len(t) <= 4000 else t[:4000]


def _max_output_chars(original: str, ratio: float) -> int:
    return int(len(original) * ratio) + 24


def _guard_improve_output(result: str, original: str) -> str:
    if not result:
        return original
    if result.strip() == original.strip():
        return result
    if len(result) > _max_output_chars(original, _IMPROVE_MAX_LENGTH_RATIO):
        return original
    if _jaccard_similarity(result, original) < _IMPROVE_MIN_JACCARD:
        return original
    if _novel_word_ratio(result, original) > _IMPROVE_MAX_NOVEL_WORD_RATIO:
        return original
    return result


def _guard_translate_improve_output(result: str, original: str) -> str:
    if not result:
        return original
    if len(result) > _max_output_chars(original, _TRANSLATE_IMPROVE_MAX_LENGTH_RATIO):
        return original
    return result


def _user_message_for_mode(mode: str, original: str, context: str) -> str:
    if mode == "improve":
        label = "message" if context == "chat" else "prompt"
        return (
            f"Original {label} (preserve meaning and wording; minimal edits only):\n"
            f"{original}"
        )
    if mode == "translate_improve":
        label = "message" if context == "chat" else "prompt"
        return (
            f"Original {label} (translate to English, then minimally improve; preserve intent):\n"
            f"{original}"
        )
    return original


def _max_tokens_for_prompt(original: str) -> int:
    return min(600, max(96, len(original) + 80))


async def enhance_user_prompt(
    db: AsyncSession,
    user: User,
    model_ref: str,
    prompt: str,
    mode: str,
    context: str = "image",
) -> str:
    """Return an enhanced/translated prompt; falls back to the original on any issue."""
    original = (prompt or "").strip()
    if not original:
        return original
    normalized_mode = _normalize_mode(mode)
    normalized_context = _normalize_context(context)
    if normalized_mode is None:
        return original
    if normalized_mode == "translate" and detect_prompt_language(original) == "en":
        return original

    system = _SYSTEM_BY_CONTEXT_AND_MODE.get(normalized_context, {}).get(normalized_mode)
    if not system:
        return original

    budget, usage = await get_user_budget_state(db, user)
    if budget_request_blocked(budget, usage):
        return original

    ai_model, api_key, base_url, provider_type = await resolve_model_and_key(db, model_ref)
    if not ai_model or not api_key:
        return original

    model = _litellm_model_for_provider(ai_model.external_id, provider_type or ai_model.provider_type)
    kwargs: dict = {
        "messages": [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": _user_message_for_mode(normalized_mode, original, normalized_context),
            },
        ],
        "api_key": api_key,
        "base_url": base_url,
        "stream": False,
        "max_tokens": _max_tokens_for_prompt(original),
        "temperature": 0.1,
    }
    _apply_litellm_provider_kwargs(kwargs, provider_type or ai_model.provider_type, model)

    try:
        response = await acompletion(**kwargs)
        content = ""
        if response.choices:
            content = getattr(response.choices[0].message, "content", None) or ""
        result = _sanitize_prompt(content, original)
        if normalized_mode == "improve":
            result = _guard_improve_output(result, original)
        elif normalized_mode == "translate_improve":
            result = _guard_translate_improve_output(result, original)
        return result
    except Exception:
        return original


async def enhance_image_generation_prompt(
    db: AsyncSession,
    user: User,
    model_ref: str,
    prompt: str,
    mode: str,
) -> str:
    """Backward-compatible wrapper for image prompt enhancement."""
    return await enhance_user_prompt(db, user, model_ref, prompt, mode, context="image")
