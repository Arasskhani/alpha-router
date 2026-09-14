"""Generate short chat session titles (ChatGPT-style overview, not first prompt verbatim)."""

import json
import re
import datetime

from litellm import acompletion
from sqlalchemy.ext.asyncio import AsyncSession

from app.branding import CHAT_CLIENT_APP
from app.models.user import User
from app.services.budget_service import budget_request_blocked, get_user_budget_state
from app.services.chat_markers import (
    ATTACHMENT_MESSAGE_PREFIX,
    AUDIO_MESSAGE_PREFIX,
    IMAGE_MESSAGE_PREFIX,
    IMAGE_PENDING_MARKER,
    VIDEO_MESSAGE_PREFIX,
    VIDEO_PENDING_MARKER,
)
from app.services.llm_providers import litellm_model_for_provider as _litellm_model_for_provider
from app.services.provider_utils import _apply_litellm_provider_kwargs
from app.services.model_resolution_service import resolve_model_and_key
from app.services.usage_logging_service import reserve_auxiliary_llm_usage, settle_auxiliary_usage

_TITLE_SYSTEM = (
    "You create short chat titles for a sidebar. Given the start of a conversation, "
    "write ONE concise title (2–4 words) that captures the overall topic or intent. "
    "Prefer the shortest clear phrase. Use the same language as the user. "
    "No quotes, no trailing punctuation, no colons."
)

_TITLE_MAX_CHARS = 40
_FALLBACK_TITLE_MAX_CHARS = 28
_FALLBACK_TITLE_MAX_WORDS = 4

_IMAGE_PREFIX = IMAGE_MESSAGE_PREFIX
_IMAGE_PENDING = IMAGE_PENDING_MARKER
_VIDEO_PREFIX = VIDEO_MESSAGE_PREFIX
_VIDEO_PENDING = VIDEO_PENDING_MARKER
_INTERNAL_TITLE_PREFIXES = (
    _IMAGE_PREFIX,
    _VIDEO_PREFIX,
    ATTACHMENT_MESSAGE_PREFIX,
    AUDIO_MESSAGE_PREFIX,
)


def _clip(text: str, limit: int = 1200) -> str:
    t = (text or "").strip()
    return t if len(t) <= limit else f"{t[: limit - 1]}…"


def _parse_json_prompt(raw: str, prefix: str, fallback: str) -> str:
    try:
        payload = json.loads(raw[len(prefix) :])
        if isinstance(payload, dict):
            prompt = str(payload.get("prompt") or "").strip()
            if prompt:
                return prompt
            transcript = str(payload.get("transcript") or "").strip()
            if transcript:
                return transcript
            user_text = str(payload.get("userText") or "").strip()
            if user_text:
                return user_text
    except Exception:  # noqa: BLE001 -- best-effort side effect, failure intentionally ignored (Phase 4: log at DEBUG)
        pass
    return fallback


def _normalize_content_for_title(content: str) -> str:
    t = (content or "").strip()
    if t in (_IMAGE_PENDING, _VIDEO_PENDING) or not t:
        return ""
    if t.startswith(_IMAGE_PREFIX):
        return _parse_json_prompt(t, _IMAGE_PREFIX, "Generated image")
    if t.startswith(_VIDEO_PREFIX):
        return _parse_json_prompt(t, _VIDEO_PREFIX, "Generated video")
    if t.startswith(ATTACHMENT_MESSAGE_PREFIX):
        return _parse_json_prompt(t, ATTACHMENT_MESSAGE_PREFIX, "")
    if t.startswith(AUDIO_MESSAGE_PREFIX):
        return _parse_json_prompt(t, AUDIO_MESSAGE_PREFIX, "")
    return t


def _format_turns(messages: list[dict]) -> str:
    lines: list[str] = []
    for m in messages[:6]:
        role = (m.get("role") or "").strip().lower()
        content = _clip(_normalize_content_for_title(str(m.get("content") or "")), 800)
        if role not in ("user", "assistant") or not content:
            continue
        label = "User" if role == "user" else "Assistant"
        lines.append(f"{label}: {content}")
    return "\n\n".join(lines) if lines else "User: (empty)"


def _sanitize_title(raw: str) -> str:
    t = (raw or "").strip().strip("\"'“”‘’")
    t = re.sub(r"\s+", " ", t)
    t = t.rstrip(".!?;:،")
    if not t:
        return "New chat"
    if any(t.startswith(p) for p in _INTERNAL_TITLE_PREFIXES):
        return "New chat"
    if '{"url":' in t and "/api/chat/media/" in t:
        return "New chat"
    if len(t) <= _TITLE_MAX_CHARS:
        return t
    return f"{t[: _TITLE_MAX_CHARS - 1]}…"


async def generate_chat_title(
    db: AsyncSession,
    user: User,
    model_ref: str,
    messages: list[dict],
) -> str:
    budget, usage = await get_user_budget_state(db, user)
    if budget_request_blocked(budget, usage):
        return _sanitize_title(_fallback_title(messages))

    ai_model, api_key, base_url, provider_type = await resolve_model_and_key(db, model_ref)
    if not ai_model or not api_key:
        return _sanitize_title(_fallback_title(messages))

    model = _litellm_model_for_provider(ai_model.external_id, provider_type or ai_model.provider_type)
    kwargs: dict = {
        "messages": [
            {"role": "system", "content": _TITLE_SYSTEM},
            {
                "role": "user",
                "content": (f"Conversation excerpt:\n\n{_format_turns(messages)}\n\nTitle:"),
            },
        ],
        "api_key": api_key,
        "base_url": base_url,
        "stream": False,
        "max_tokens": 32,
        "temperature": 0.2,
    }
    _apply_litellm_provider_kwargs(kwargs, provider_type or ai_model.provider_type, model)

    reservation_id: str | None = None
    try:
        reservation_id = await reserve_auxiliary_llm_usage(
            db,
            user_id=user.id,
            ai_model=ai_model,
            operation_name="chat_title",
            messages=kwargs["messages"],
            max_tokens=32,
        )
    except Exception:  # noqa: BLE001 -- external/optional dependency; falls back (return _sanitize_title(_fallback_title(m)
        return _sanitize_title(_fallback_title(messages))

    response = None
    success = False
    error_message: str | None = None
    completion_text = ""
    started_at = datetime.datetime.utcnow()
    try:
        response = await acompletion(**kwargs)
        content = ""
        if response.choices:
            content = getattr(response.choices[0].message, "content", None) or ""
        completion_text = content
        title = _sanitize_title(content or _fallback_title(messages))
        success = True
        if title == "New chat":
            return _sanitize_title(_fallback_title(messages))
        return title
    except Exception as exc:  # noqa: BLE001 -- error text is surfaced to the caller
        error_message = str(exc)[:500]
        return _sanitize_title(_fallback_title(messages))
    finally:
        await settle_auxiliary_usage(
            user_id=user.id,
            username=user.username,
            ai_model=ai_model,
            provider_type=provider_type,
            model_id=model,
            response=response,
            prompt=kwargs["messages"],
            completion=completion_text,
            operation_name="chat_title",
            client_app=f"{CHAT_CLIENT_APP} (helper:title)",
            budget_reservation_id=reservation_id,
            success=success,
            error_message=error_message,
            started_at=started_at,
        )


def _clip_fallback(text: str) -> str:
    t = re.sub(r"\s+", " ", (text or "").replace("\n", " ")).strip()
    if not t:
        return "New chat"
    words = t.split()
    if len(words) > _FALLBACK_TITLE_MAX_WORDS:
        t = " ".join(words[:_FALLBACK_TITLE_MAX_WORDS])
    if len(t) <= _FALLBACK_TITLE_MAX_CHARS:
        return t
    return f"{t[: _FALLBACK_TITLE_MAX_CHARS - 1]}…"


def _fallback_title(messages: list[dict]) -> str:
    for m in messages:
        if m.get("role") != "user":
            continue
        c = _normalize_content_for_title(str(m.get("content", "")))
        if not c:
            continue
        return _clip_fallback(c)

    for m in messages:
        if m.get("role") != "assistant":
            continue
        c = _normalize_content_for_title(str(m.get("content", "")))
        if not c:
            continue
        words = c.split()
        if len(words) >= 2:
            return _clip_fallback(" ".join(words[:_FALLBACK_TITLE_MAX_WORDS]))

    return "New chat"
