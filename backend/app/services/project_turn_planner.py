"""Inject project prompt, memory, and resource excerpts into a chat turn.

Only ``ChatSession.project_id`` authorizes injection. A client-supplied
``project_id`` is never trusted. Failures here must not fail the turn.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat import ChatSession, is_member_channel
from app.models.knowledge import KnowledgeChunk, KnowledgeDocument, KnowledgeDocumentVersion
from app.models.project import (
    PROJECT_RESOURCE_STATUS_REVOKED,
    Project,
    ProjectConfigVersion,
    ProjectResource,
)
from app.models.user import User
from app.services.knowledge_crypto_service import decrypt_text
from app.services.project_access_service import resolve_project_access
from app.services.project_memory_service import (
    ProjectMemoryInjection,
    format_project_memory_block,
    load_injectable_project_memories,
)

logger = logging.getLogger("app.services.project_turn_planner")

_MAX_GROUNDING_SCAN = 80
_MAX_GROUNDING_CHUNKS = 4
_MAX_GROUNDING_CHARS = 6_000
_TOKEN_RE = re.compile(r"[A-Za-z0-9\u0600-\u06FF]{3,}")


def _message_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict):
                text = part.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(parts)
    return ""


def _last_user_query(messages: list[dict]) -> str:
    for item in reversed(messages):
        if not isinstance(item, dict):
            continue
        if str(item.get("role") or "") != "user":
            continue
        text = _message_text(item.get("content")).strip()
        if text:
            return text
    return ""


def _policy_flag(policy: dict, key: str, *, default: bool) -> bool:
    if key not in policy:
        return default
    value = policy.get(key)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in ("0", "false", "no", "off"):
            return False
        if lowered in ("1", "true", "yes", "on"):
            return True
    return default


def _merge_system_block(messages: list[dict], block: str) -> list[dict]:
    if not block.strip():
        return messages
    out = list(messages)
    if out and out[0].get("role") == "system" and isinstance(out[0].get("content"), str):
        out[0] = {
            "role": "system",
            "content": f"{out[0]['content']}\n\n{block}",
        }
        return out
    return [{"role": "system", "content": block}, *out]


def _score_chunk(query: str, text: str) -> int:
    q_tokens = set(_TOKEN_RE.findall(query.lower()))
    if not q_tokens:
        return 0
    t_tokens = set(_TOKEN_RE.findall(text.lower()))
    return len(q_tokens & t_tokens)


async def _load_active_config(
    db: AsyncSession, project_id: str
) -> tuple[str | None, bool, dict]:
    """Return (custom_prompt, memory_enabled, grounding_policy) without HTTP errors."""

    project = await db.get(Project, project_id)
    if project is None or not project.active_config_version_id:
        return None, True, {}
    version = await db.get(ProjectConfigVersion, project.active_config_version_id)
    if version is None:
        return None, True, {}
    prompt = (version.custom_prompt or "").strip() or None
    return prompt, bool(version.memory_enabled), dict(version.grounding_policy or {})


async def _load_project_resource_excerpts(
    db: AsyncSession,
    *,
    project_id: str,
    query: str,
) -> list[tuple[str, str]]:
    """Return (title, excerpt) pairs from published project Knowledge chunks.

    Uses the Knowledge version status (not the denormalized resource row)
    so a published file is injectable even if ``project_resources.status``
    has not been synced yet. Unencrypted chunk rows are rejected by
    ``decrypt_text``.
    """

    rows = (
        await db.execute(
            select(ProjectResource, KnowledgeDocument, KnowledgeChunk)
            .join(
                KnowledgeDocument,
                KnowledgeDocument.id == ProjectResource.document_id,
            )
            .join(
                KnowledgeDocumentVersion,
                KnowledgeDocumentVersion.document_id == KnowledgeDocument.id,
            )
            .join(
                KnowledgeChunk,
                KnowledgeChunk.document_version_id == KnowledgeDocumentVersion.id,
            )
            .where(
                ProjectResource.project_id == project_id,
                ProjectResource.status != PROJECT_RESOURCE_STATUS_REVOKED,
                KnowledgeDocument.status.notin_(("deleted", "revoked")),
                KnowledgeDocumentVersion.status == "published",
            )
            .order_by(
                KnowledgeDocumentVersion.version_number.desc(),
                KnowledgeChunk.chunk_index.asc(),
            )
            .limit(_MAX_GROUNDING_SCAN)
        )
    ).all()

    scored: list[tuple[int, int, str, str]] = []
    for index, (resource, document, chunk) in enumerate(rows):
        try:
            text = decrypt_text(
                chunk.content,
                associated_data=f"knowledge-chunk:{chunk.id}",
            ).strip()
        except Exception:
            continue
        if not text:
            continue
        title = (resource.title or document.title or "Resource").strip() or "Resource"
        scored.append((_score_chunk(query, text), -index, title, text))

    if not scored:
        return []
    scored.sort(reverse=True)

    picked: list[tuple[str, str]] = []
    total = 0
    for _score, _order, title, text in scored[:_MAX_GROUNDING_CHUNKS]:
        excerpt = text[:1500]
        cost = len(excerpt) + len(title)
        if total + cost > _MAX_GROUNDING_CHARS:
            break
        picked.append((title, excerpt))
        total += cost
    return picked


def _format_custom_prompt_block(prompt: str) -> str:
    return (
        "## Project instructions\n"
        "Follow these project-specific instructions for this conversation.\n\n"
        f"{prompt.strip()}"
    )


def _format_resource_block(excerpts: list[tuple[str, str]]) -> str:
    lines = [
        "## Project resources",
        "Excerpts from files attached to this project. Use them when relevant; "
        "they are not the full documents.",
    ]
    for title, excerpt in excerpts:
        lines.append("")
        lines.append(f"### {title}")
        lines.append(excerpt)
    return "\n".join(lines)


async def plan_project_turn(
    db: AsyncSession,
    messages: list[dict],
    *,
    user_id: int | None,
    chat_session_id: str | None,
    client_project_id: str | None = None,
    query: str | None = None,
    injected_memory_ids: list[str] | None = None,
) -> list[dict]:
    """Inject project system context when the *session* belongs to a project.

    ``client_project_id`` is ignored. Personal chats receive no project blocks.
    """

    del client_project_id  # never trusted for injection
    sid = (chat_session_id or "").strip()
    if not sid or user_id is None:
        return messages

    session = await db.get(ChatSession, sid)
    if session is None or not session.project_id:
        return messages
    if session.private_mode or is_member_channel(session):
        return messages

    user = await db.get(User, user_id)
    if user is None:
        return messages
    access = await resolve_project_access(
        db, project_id=session.project_id, user=user
    )
    if access is None or not access.can("project.view"):
        return messages

    custom_prompt, memory_enabled, grounding_policy = await _load_active_config(
        db, session.project_id
    )
    blocks: list[str] = []
    if custom_prompt:
        blocks.append(_format_custom_prompt_block(custom_prompt))

    # A public viewer chats through the project's prompt but must not receive
    # its memory: the model would happily repeat it back.
    if memory_enabled and access.can("memory.read"):
        injection = await load_injectable_project_memories(
            db,
            project_id=session.project_id,
            memory_enabled=True,
            query=query if query is not None else _last_user_query(messages),
        )
        if not _policy_flag(grounding_policy, "useGrantedMemory", default=True):
            injection = ProjectMemoryInjection(
                own_facts=injection.own_facts,
                granted_facts=(),
                total_facts=len(injection.own_facts) + len(injection.auto_facts),
                auto_facts=injection.auto_facts,
                memory_ids=injection.memory_ids,
            )
        if injection.total_facts:
            blocks.append(format_project_memory_block(injection))
            if injected_memory_ids is not None:
                injected_memory_ids.extend(injection.memory_ids)

    if _policy_flag(grounding_policy, "useProjectResources", default=True):
        try:
            excerpts = await _load_project_resource_excerpts(
                db,
                project_id=session.project_id,
                query=_last_user_query(messages),
            )
        except Exception:
            logger.exception(
                "Project resource grounding failed project=%s session=%s",
                session.project_id,
                sid,
            )
            excerpts = []
        if excerpts:
            blocks.append(_format_resource_block(excerpts))

    if not blocks:
        return messages
    return _merge_system_block(messages, "\n\n".join(blocks))


async def augment_messages_with_project_context(
    db: AsyncSession,
    messages: list[dict],
    *,
    user_id: int | None,
    chat_session_id: str | None,
    client_project_id: str | None = None,
    query: str | None = None,
    injected_memory_ids: list[str] | None = None,
) -> list[dict]:
    """Best-effort wrapper used by the chat proxy and Agent planner."""

    try:
        return await plan_project_turn(
            db,
            messages,
            user_id=user_id,
            chat_session_id=chat_session_id,
            client_project_id=client_project_id,
            query=query,
            injected_memory_ids=injected_memory_ids,
        )
    except Exception:
        logger.exception(
            "Project turn planning failed session=%s; continuing without project context",
            chat_session_id,
        )
        return messages
