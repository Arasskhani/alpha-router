"""Generate short chat session titles (ChatGPT-style overview, not first prompt verbatim)."""

import json
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

_TITLE_SYSTEM = (
    "You create short chat titles for a sidebar. Given the start of a conversation, "
    "write ONE concise title (3–7 words) that captures the overall topic or intent. "
    "Use the same language as the user. No quotes, no trailing punctuation, no colons."
)

_IMAGE_PREFIX = "__ALPHA_ROUTER_IMAGE_JSON__:"
_IMAGE_PENDING = "__ALPHA_ROUTER_IMAGE_PENDING__"
_INTERNAL_TITLE_PREFIXES = (
    _IMAGE_PREFIX,
    "__ALPHA_ROUTER_IMAGE_JSON__:",
    "__ALPHA_ROUTER_IMAGE__:",
    "__ALPHA_ROUTER_IMAGE__:",
    "__ALPHA_ROUTER_ATTACH_JSON__:",
    "__ALPHA_ROUTER_AUDIO_JSON__:",
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
    except Exception:
        pass
    return fallback


def _normalize_content_for_title(content: str) -> str:
    t = (content or "").strip()
    if not t or t == _IMAGE_PENDING:
        return ""
    if t.startswith(_IMAGE_PREFIX):
        return _parse_json_prompt(t, _IMAGE_PREFIX, "Generated image")
    if t.startswith("__ALPHA_ROUTER_IMAGE_JSON__:"):
        return _parse_json_prompt(t, "__ALPHA_ROUTER_IMAGE_JSON__:", "Generated image")
    if t.startswith("__ALPHA_ROUTER_IMAGE__:") or t.startswith("__ALPHA_ROUTER_IMAGE__:"):
        return "Generated image"
    if t.startswith("__ALPHA_ROUTER_ATTACH_JSON__:"):
        return _parse_json_prompt(t, "__ALPHA_ROUTER_ATTACH_JSON__:", "")
    if t.startswith("__ALPHA_ROUTER_AUDIO_JSON__:"):
        return _parse_json_prompt(t, "__ALPHA_ROUTER_AUDIO_JSON__:", "")
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
    return t if len(t) <= 80 else f"{t[:79]}…"


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
                "content": (
                    "Conversation excerpt:\n\n"
                    f"{_format_turns(messages)}\n\n"
                    "Title:"
                ),
            },
        ],
        "api_key": api_key,
        "base_url": base_url,
        "stream": False,
        "max_tokens": 32,
        "temperature": 0.2,
    }
    _apply_litellm_provider_kwargs(kwargs, provider_type or ai_model.provider_type, model)

    try:
        response = await acompletion(**kwargs)
        content = ""
        if response.choices:
            content = getattr(response.choices[0].message, "content", None) or ""
        title = _sanitize_title(content or _fallback_title(messages))
        if title == "New chat":
            return _sanitize_title(_fallback_title(messages))
        return title
    except Exception:
        return _sanitize_title(_fallback_title(messages))


def _fallback_title(messages: list[dict]) -> str:
    for m in messages:
        if m.get("role") != "user":
            continue
        c = _normalize_content_for_title(str(m.get("content", "")))
        if not c:
            continue
        t = c.replace("\n", " ")
        return t if len(t) <= 42 else f"{t[:41]}…"

    for m in messages:
        if m.get("role") != "assistant":
            continue
        c = _normalize_content_for_title(str(m.get("content", "")))
        if not c:
            continue
        words = c.split()
        if len(words) >= 2:
            snippet = " ".join(words[:7])
            return snippet if len(snippet) <= 42 else f"{snippet[:41]}…"

    return "New chat"
