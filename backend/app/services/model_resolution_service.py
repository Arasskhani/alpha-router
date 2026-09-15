"""Resolve a requested model id to a catalog row, its connection secret and route (Phase 4.1).

Shared by the chat proxy, helper LLM calls (titles, prompt assist) and the
memory extraction jobs. Lived in ``proxy_service`` and was imported lazily
from three services.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.connection import Connection
from app.models.model_catalog import AIModel
from app.services.llm_providers import external_id_lookup_candidates, normalize_model_id
from app.services.model_capabilities import model_kinds, model_media_flags
from app.services.model_tool_compatibility_service import is_auto_router_model_id
from app.services.secret_crypto import decrypt_secret


async def resolve_model_and_key(
    db: AsyncSession,
    model_id: str,
    *,
    allowed_connection_ids: set[int] | None = None,
    allowed_model_ids: set[int] | None = None,
) -> tuple[AIModel | None, str | None, str | None, str | None]:
    if allowed_connection_ids is not None and not allowed_connection_ids:
        return None, None, None, None
    if allowed_model_ids is not None and not allowed_model_ids:
        return None, None, None, None

    connection_filter: tuple[Any, ...] = ()
    if allowed_connection_ids is not None:
        connection_filter = (AIModel.connection_id.in_(allowed_connection_ids),)
    model_filter: tuple[Any, ...] = ()
    if allowed_model_ids is not None:
        model_filter = (AIModel.id.in_(allowed_model_ids),)

    normalized_input = normalize_model_id(model_id)
    row: AIModel | None = None
    if isinstance(normalized_input, str) and normalized_input.startswith("model::"):
        try:
            model_pk = int(normalized_input.split("::", 1)[1])
        except Exception:  # noqa: BLE001 -- falls back to a safe default value
            model_pk = None
        if model_pk is not None:
            row = (
                (
                    await db.execute(
                        select(AIModel)
                        .join(Connection, Connection.id == AIModel.connection_id)
                        .where(
                            AIModel.id == model_pk,
                            AIModel.is_enabled == True,  # noqa: E712
                            Connection.is_active == True,  # noqa: E712
                            *connection_filter,
                            *model_filter,
                        )
                        .order_by(AIModel.id.asc())
                    )
                )
                .scalars()
                .first()
            )
    if not row:
        candidates = external_id_lookup_candidates(normalized_input)
        if candidates:
            row = (
                (
                    await db.execute(
                        select(AIModel)
                        # The same external id can exist on several connections;
                        # picking the lowest id and *then* checking its connection
                        # returned "no model" when that one was disabled even
                        # though an active twin existed. Filter first.
                        .join(Connection, Connection.id == AIModel.connection_id)
                        .where(
                            AIModel.external_id.in_(candidates),
                            AIModel.is_enabled == True,  # noqa: E712
                            Connection.is_active == True,  # noqa: E712
                            *connection_filter,
                            *model_filter,
                        )
                        .order_by(AIModel.id.asc())
                    )
                )
                .scalars()
                .first()
            )
    if not row:
        return None, None, None, None
    if allowed_connection_ids is not None and int(row.connection_id) not in allowed_connection_ids:
        return None, None, None, None
    if allowed_model_ids is not None and int(row.id) not in allowed_model_ids:
        return None, None, None, None
    conn = await db.get(Connection, row.connection_id)
    if not conn or not conn.is_active:
        return None, None, None, None
    return (
        row,
        decrypt_secret(conn.api_key_encrypted),
        conn.base_url,
        conn.provider_type,
    )


def assert_model_supports_text_chat(ai_model: AIModel) -> None:
    """Reject embeddings/rerank/media-only models from the chat-completions path."""
    if is_auto_router_model_id(ai_model.external_id):
        return
    media = model_media_flags(
        external_id=ai_model.external_id or "",
        is_image_model=bool(ai_model.is_image_model),
        is_video_model=bool(getattr(ai_model, "is_video_model", False)),
        pricing_raw=ai_model.pricing_raw,
        provider_type=ai_model.provider_type,
    )
    kinds = model_kinds(
        external_id=ai_model.external_id or "",
        is_image_model=media["is_image_model"],
        is_video_model=media["is_video_model"],
        pricing_raw=ai_model.pricing_raw,
        provider_type=ai_model.provider_type,
    )
    if "text" in kinds:
        return
    kind_label = ", ".join(kinds) if kinds else "unknown"
    raise HTTPException(
        status_code=400,
        detail={
            "message": (
                f"This model is not available for text chat (capabilities: {kind_label}). Choose a text model instead."
            ),
            "code": "model_not_for_chat",
            "kinds": kinds,
        },
    )
