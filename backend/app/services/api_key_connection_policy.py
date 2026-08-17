"""Connection allowlist for gateway API keys."""

from __future__ import annotations

from sqlalchemy import delete, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.api_key import AlphaRouterApiKey, alpha_router_api_key_connections
from app.models.connection import Connection
from app.models.model_catalog import AIModel


async def allowed_connection_ids_for_key(
    db: AsyncSession, alpha_router_api_key_id: int | None
) -> set[int] | None:
    """None = unrestricted. Empty set = restricted to no connections."""
    if alpha_router_api_key_id is None:
        return None
    key = await db.get(AlphaRouterApiKey, int(alpha_router_api_key_id))
    if key is None or not key.restrict_connections:
        return None
    rows = (
        (
            await db.execute(
                select(alpha_router_api_key_connections.c.connection_id).where(
                    alpha_router_api_key_connections.c.alpha_router_api_key_id
                    == int(alpha_router_api_key_id)
                )
            )
        )
        .scalars()
        .all()
    )
    return {int(cid) for cid in rows}


def filter_models_for_connections(
    models: list[AIModel], allowed_connection_ids: set[int] | None
) -> list[AIModel]:
    if allowed_connection_ids is None:
        return models
    allowed = allowed_connection_ids
    return [m for m in models if int(m.connection_id) in allowed]


def connection_policy_label(restrict: bool, names: list[str]) -> str:
    if not restrict:
        return "All connections"
    cleaned = [n for n in names if n]
    if not cleaned:
        return "None"
    return ", ".join(cleaned)


def connection_brief(conn: Connection) -> dict:
    return {
        "id": conn.id,
        "name": conn.name,
        "provider_type": conn.provider_type,
        "is_active": bool(conn.is_active),
    }


async def map_allowed_connections(
    db: AsyncSession, key_ids: list[int]
) -> dict[int, list[dict]]:
    out: dict[int, list[dict]] = {int(kid): [] for kid in key_ids}
    if not key_ids:
        return out
    rows = (
        await db.execute(
            select(
                alpha_router_api_key_connections.c.alpha_router_api_key_id,
                Connection,
            )
            .join(
                Connection,
                Connection.id == alpha_router_api_key_connections.c.connection_id,
            )
            .where(
                alpha_router_api_key_connections.c.alpha_router_api_key_id.in_(
                    [int(kid) for kid in key_ids]
                )
            )
            .order_by(Connection.name.asc(), Connection.id.asc())
        )
    ).all()
    for key_id, conn in rows:
        out.setdefault(int(key_id), []).append(connection_brief(conn))
    return out


async def replace_key_allowed_connections(
    db: AsyncSession,
    key: AlphaRouterApiKey,
    *,
    restrict: bool,
    connection_ids: list[int],
) -> list[str]:
    """Apply policy, replace join rows, and return sorted connection names."""
    key.restrict_connections = bool(restrict)
    await db.execute(
        delete(alpha_router_api_key_connections).where(
            alpha_router_api_key_connections.c.alpha_router_api_key_id == int(key.id)
        )
    )
    if not restrict:
        return []

    clean = list(dict.fromkeys(int(x) for x in connection_ids))
    if not clean:
        return []

    rows = (await db.execute(select(Connection).where(Connection.id.in_(clean)))).scalars().all()
    found = {int(c.id): c for c in rows}
    missing = [cid for cid in clean if cid not in found]
    if missing:
        raise ValueError(f"Unknown connection id(s): {', '.join(str(x) for x in missing)}")

    await db.execute(
        insert(alpha_router_api_key_connections),
        [
            {"alpha_router_api_key_id": int(key.id), "connection_id": cid}
            for cid in clean
        ],
    )
    return [found[cid].name for cid in sorted(clean, key=lambda i: found[i].name.lower())]
