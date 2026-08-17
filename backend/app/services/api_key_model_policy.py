"""Model allowlist for gateway API keys."""

from __future__ import annotations

from sqlalchemy import delete, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.api_key import AlphaRouterApiKey, alpha_router_api_key_models
from app.models.connection import Connection
from app.models.model_catalog import AIModel
from app.services.api_key_connection_policy import allowed_connection_ids_for_key
from app.services.model_access_service import (
    filter_models_for_subject,
    resolve_access_subject,
    user_can_access_model,
)


async def allowed_model_ids_for_key(
    db: AsyncSession, alpha_router_api_key_id: int | None
) -> set[int] | None:
    """None = unrestricted. Empty set = restricted to no models."""
    if alpha_router_api_key_id is None:
        return None
    key = await db.get(AlphaRouterApiKey, int(alpha_router_api_key_id))
    if key is None or not key.restrict_models:
        return None
    rows = (
        (
            await db.execute(
                select(alpha_router_api_key_models.c.model_id).where(
                    alpha_router_api_key_models.c.alpha_router_api_key_id
                    == int(alpha_router_api_key_id)
                )
            )
        )
        .scalars()
        .all()
    )
    return {int(mid) for mid in rows}


def filter_models_for_allowlist(
    models: list[AIModel], allowed_model_ids: set[int] | None
) -> list[AIModel]:
    if allowed_model_ids is None:
        return models
    allowed = allowed_model_ids
    return [m for m in models if int(m.id) in allowed]


def model_policy_label(restrict: bool, labels: list[str]) -> str:
    if not restrict:
        return "All models"
    cleaned = [label for label in labels if label]
    if not cleaned:
        return "None"
    return ", ".join(cleaned)


def model_brief(model: AIModel, *, connection_name: str | None = None) -> dict:
    label = (model.display_name or model.external_id or "").strip()
    return {
        "id": model.id,
        "external_id": model.external_id,
        "display_name": label or model.external_id,
        "connection_id": model.connection_id,
        "connection_name": connection_name,
        "provider_type": model.provider_type,
        "is_enabled": bool(model.is_enabled),
    }


async def map_allowed_models(db: AsyncSession, key_ids: list[int]) -> dict[int, list[dict]]:
    out: dict[int, list[dict]] = {int(kid): [] for kid in key_ids}
    if not key_ids:
        return out
    rows = (
        await db.execute(
            select(
                alpha_router_api_key_models.c.alpha_router_api_key_id,
                AIModel,
                Connection.name,
            )
            .join(AIModel, AIModel.id == alpha_router_api_key_models.c.model_id)
            .join(Connection, Connection.id == AIModel.connection_id)
            .where(
                alpha_router_api_key_models.c.alpha_router_api_key_id.in_(
                    [int(kid) for kid in key_ids]
                )
            )
            .order_by(AIModel.external_id.asc(), AIModel.id.asc())
        )
    ).all()
    for key_id, model, connection_name in rows:
        out.setdefault(int(key_id), []).append(
            model_brief(model, connection_name=connection_name)
        )
    return out


async def list_picker_models(
    db: AsyncSession,
    *,
    owner_user_id: int,
    connection_ids: list[int] | None = None,
) -> list[dict]:
    stmt = (
        select(AIModel, Connection.name)
        .join(Connection, Connection.id == AIModel.connection_id)
        .where(AIModel.is_enabled == True, Connection.is_active == True)  # noqa: E712
    )
    if connection_ids:
        clean = list(dict.fromkeys(int(x) for x in connection_ids))
        stmt = stmt.where(AIModel.connection_id.in_(clean))
    rows = (await db.execute(stmt.order_by(AIModel.external_id.asc(), AIModel.id.asc()))).all()
    models = [model for model, _ in rows]
    conn_names = {model.id: name for model, name in rows}
    subject = await resolve_access_subject(db, user_id=owner_user_id)
    filtered = await filter_models_for_subject(db, models, subject)
    return [
        model_brief(m, connection_name=conn_names.get(m.id))
        for m in filtered
    ]


async def replace_key_allowed_models(
    db: AsyncSession,
    key: AlphaRouterApiKey,
    *,
    restrict: bool,
    model_ids: list[int],
) -> list[str]:
    """Apply policy, replace join rows, and return sorted model labels."""
    key.restrict_models = bool(restrict)
    await db.execute(
        delete(alpha_router_api_key_models).where(
            alpha_router_api_key_models.c.alpha_router_api_key_id == int(key.id)
        )
    )
    if not restrict:
        return []

    clean = list(dict.fromkeys(int(x) for x in model_ids))
    if not clean:
        return []

    rows = (
        await db.execute(
            select(AIModel, Connection.name)
            .join(Connection, Connection.id == AIModel.connection_id)
            .where(AIModel.id.in_(clean))
        )
    ).all()
    found = {int(model.id): (model, conn_name) for model, conn_name in rows}
    missing = [mid for mid in clean if mid not in found]
    if missing:
        raise ValueError(f"Unknown model id(s): {', '.join(str(x) for x in missing)}")

    allowed_connection_ids = await allowed_connection_ids_for_key(db, int(key.id))
    if allowed_connection_ids is not None:
        for mid in clean:
            model, _ = found[mid]
            if int(model.connection_id) not in allowed_connection_ids:
                raise ValueError(
                    f"Model {model.external_id} is not on an allowed connection for this key"
                )

    if key.owner_user_id is not None:
        subject = await resolve_access_subject(
            db,
            user_id=int(key.owner_user_id),
        )
        for mid in clean:
            model, _ = found[mid]
            if not await user_can_access_model(db, model, subject):
                raise ValueError(
                    f"Owner cannot access model {model.external_id}"
                )
    elif clean:
        raise ValueError("Select an owner before restricting models on this key")

    await db.execute(
        insert(alpha_router_api_key_models),
        [
            {"alpha_router_api_key_id": int(key.id), "model_id": mid}
            for mid in clean
        ],
    )
    labels: list[str] = []
    for mid in sorted(clean, key=lambda i: (found[i][0].external_id or "").lower()):
        model, conn_name = found[mid]
        label = model.display_name or model.external_id
        if conn_name:
            label = f"{label} ({conn_name})"
        labels.append(label)
    return labels
