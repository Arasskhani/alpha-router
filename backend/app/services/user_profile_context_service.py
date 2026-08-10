"""Directory/HR profile fields injected into non-private chat completions."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User

_MAX_FIELD_CHARS = 255

# Stable order for UI + prompt injection.
_PROFILE_FIELDS: tuple[tuple[str, str], ...] = (
    ("company", "Company"),
    ("department", "Department"),
    ("job_title", "Job title"),
    ("reporting_to", "Report to"),
)


def _clean_field(value: str | None) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).split()).strip()
    if not text:
        return None
    return text[:_MAX_FIELD_CHARS]


def profile_facts_from_user(user: User | None) -> list[tuple[str, str]]:
    """Return ordered (label, value) pairs for injectable profile fields."""
    if user is None:
        return []
    facts: list[tuple[str, str]] = []
    for attr, label in _PROFILE_FIELDS:
        cleaned = _clean_field(getattr(user, attr, None))
        if cleaned:
            facts.append((label, cleaned))
    return facts


def format_profile_system_block(facts: list[tuple[str, str]]) -> str:
    lines = [
        "## User profile",
        "The following directory attributes are from the user's account. Use them when relevant.",
        "Do not invent additional organizational details.",
    ]
    for label, value in facts:
        lines.append(f"- {label}: {value}")
    return "\n".join(lines)


def profile_payload(user: User | None) -> dict[str, str | None]:
    facts = {label: value for label, value in profile_facts_from_user(user)}
    return {
        "company": facts.get("Company"),
        "department": facts.get("Department"),
        "job_title": facts.get("Job title"),
        "reporting_to": facts.get("Report to"),
    }


async def augment_messages_with_profile(
    db: AsyncSession,
    messages: list[dict],
    *,
    user_id: int | None,
    private_mode: bool = False,
) -> list[dict]:
    """Prepend/merge account profile context. Never mutates non-system turns."""
    if user_id is None or private_mode:
        return messages
    user = await db.get(User, user_id)
    facts = profile_facts_from_user(user)
    if not facts:
        return messages
    block = format_profile_system_block(facts)
    out = list(messages)
    if out and out[0].get("role") == "system" and isinstance(out[0].get("content"), str):
        out[0] = {
            "role": "system",
            "content": f"{out[0]['content']}\n\n{block}",
        }
        return out
    return [{"role": "system", "content": block}, *out]
