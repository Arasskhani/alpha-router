"""Refine a voice-message transcript via a lightweight LLM pass.

Layer 4 of the voice-accuracy improvement: after speech-to-text (Whisper) produces
a transcript, an LLM corrects obvious recognition errors using the conversation
context. Output is guarded to prevent over-correction / hallucination.
"""

from __future__ import annotations

import re

from litellm import acompletion
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.services.budget_service import budget_request_blocked, get_user_budget_state
from app.services.proxy_service import (
    _apply_litellm_provider_kwargs,
    _litellm_model_for_provider,
    resolve_model_and_key,
)

_REFINE_SYSTEM = (
    "You correct speech-to-text transcription errors in a voice message. The transcript "
    "was produced by automatic speech recognition and may contain misheard words.\n\n"
    "Rules:\n"
    "- Keep the SAME language and script as the input (e.g. Persian stays Persian, "
    "English stays English). Do NOT translate.\n"
    "- Fix ONLY obvious recognition errors, using the conversation context when helpful.\n"
    "- If a word in the transcript closely matches a term from the conversation context, "
    "prefer the context term.\n"
    "- Preserve the speaker's exact meaning, intent, tone, and wording order.\n"
    "- Do NOT add new information, questions, or details not present in the transcript.\n"
    "- Do NOT rewrite or paraphrase. Make MINIMAL corrections only.\n"
    "- If the transcript is already correct, return it UNCHANGED.\n"
    "- Output may be at most ~10% longer than the input.\n\n"
    "Return ONLY the corrected transcript with no quotes, no preamble, no explanation."
)

_WORD_RE = re.compile(r"[\w\u0600-\u06FF]+", re.UNICODE)

_REFINE_MAX_LENGTH_RATIO = 1.15
_REFINE_MIN_JACCARD = 0.55
_REFINE_MAX_NOVEL_WORD_RATIO = 0.25

_MAX_CONTEXT_MESSAGES = 6
_MAX_CONTEXT_CHARS_PER_MSG = 300
_MAX_TRANSCRIPT_CHARS = 2000


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


def _sanitize(raw: str, fallback: str) -> str:
    t = (raw or "").strip().strip("\"'“”‘’")
    t = re.sub(r"\s+\n", "\n", t).strip()
    if not t:
        return fallback
    return t if len(t) <= 4000 else t[:4000]


def _guard_refine_output(result: str, original: str) -> str:
    """Reject over-correction; fall back to the original transcript."""
    if not result:
        return original
    if result.strip() == original.strip():
        return result
    if len(result) > int(len(original) * _REFINE_MAX_LENGTH_RATIO) + 24:
        return original
    if _jaccard_similarity(result, original) < _REFINE_MIN_JACCARD:
        return original
    if _novel_word_ratio(result, original) > _REFINE_MAX_NOVEL_WORD_RATIO:
        return original
    return result


def _build_context_block(context: list[dict] | None) -> str:
    if not context:
        return ""
    lines: list[str] = []
    for msg in context[-_MAX_CONTEXT_MESSAGES:]:
        role = (msg.get("role") or "").strip().lower() or "user"
        content = (msg.get("content") or "").strip()
        if not content:
            continue
        if len(content) > _MAX_CONTEXT_CHARS_PER_MSG:
            content = content[:_MAX_CONTEXT_CHARS_PER_MSG] + "…"
        lines.append(f"{role}: {content}")
    return "\n".join(lines)


def _max_tokens_for_transcript(transcript: str) -> int:
    return min(800, max(120, len(transcript) + 100))


async def refine_voice_transcript(
    db: AsyncSession,
    user: User,
    model_ref: str,
    transcript: str,
    context: list[dict] | None = None,
) -> str:
    """Return a corrected transcript; falls back to the original on any issue."""
    original = (transcript or "").strip()
    if not original:
        return original
    if len(original) > _MAX_TRANSCRIPT_CHARS:
        # Very long transcripts are left untouched to bound cost and risk.
        return original

    budget, usage = await get_user_budget_state(db, user)
    if budget_request_blocked(budget, usage):
        return original

    ai_model, api_key, base_url, provider_type = await resolve_model_and_key(db, model_ref)
    if not ai_model or not api_key:
        return original

    model = _litellm_model_for_provider(ai_model.external_id, provider_type or ai_model.provider_type)

    context_block = _build_context_block(context)
    user_content = (
        f"Conversation context (use only to fix recognition errors):\n{context_block}\n\n"
        f"Transcript to correct (preserve meaning; minimal edits only):\n{original}"
    ) if context_block else (
        f"Transcript to correct (preserve meaning; minimal edits only):\n{original}"
    )

    kwargs: dict = {
        "messages": [
            {"role": "system", "content": _REFINE_SYSTEM},
            {"role": "user", "content": user_content},
        ],
        "api_key": api_key,
        "base_url": base_url,
        "stream": False,
        "max_tokens": _max_tokens_for_transcript(original),
        "temperature": 0.1,
    }
    _apply_litellm_provider_kwargs(kwargs, provider_type or ai_model.provider_type, model)

    try:
        response = await acompletion(**kwargs)
        content = ""
        if response.choices:
            content = getattr(response.choices[0].message, "content", None) or ""
        result = _sanitize(content, original)
        return _guard_refine_output(result, original)
    except Exception:
        return original
