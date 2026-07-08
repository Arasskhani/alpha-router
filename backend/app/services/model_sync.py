"""Sync model catalogs and provider-native pricing from connections."""

import json
from datetime import datetime

import httpx
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.connection import Connection
from app.models.model_catalog import AIModel


def _per_1k_from_openrouter_pricing(pricing) -> tuple[float | None, float | None]:
    """OpenRouter returns USD per token; normalize to per 1K tokens."""
    if isinstance(pricing, list):
        pricing = pricing[0] if pricing else {}
    if not isinstance(pricing, dict):
        return None, None
    try:
        prompt = float(pricing.get("prompt", 0))
        completion = float(pricing.get("completion", 0))
        # OpenRouter uses negative values (e.g. -1) for unknown/dynamic pricing.
        in_1k = None if prompt < 0 else prompt * 1000
        out_1k = None if completion < 0 else completion * 1000
        return in_1k, out_1k
    except (TypeError, ValueError):
        return None, None


def _guess_is_image_model(ext_id: str) -> bool:
    low = (ext_id or "").lower()
    return any(
        hint in low
        for hint in (
            "image",
            "dall-e",
            "dalle",
            "flux",
            "sdxl",
            "stable-diffusion",
            "nanobanana",
        )
    )


async def fetch_openrouter_models(api_key: str, base_url: str | None) -> list[dict]:
    url = (base_url or "https://openrouter.ai/api/v1").rstrip("/") + "/models"
    headers = {"Authorization": f"Bearer {api_key}"}
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.get(url, headers=headers)
        resp.raise_for_status()
        return resp.json().get("data", [])


async def sync_connection_models(db: AsyncSession, conn: Connection, api_key: str) -> int:
    """Upsert models for a connection; pricing copied verbatim from provider response."""
    provider = conn.provider_type.lower()
    synced = 0

    if provider == "openrouter":
        items = await fetch_openrouter_models(api_key, conn.base_url)
        for m in items:
            ext_id = m.get("id")
            if not ext_id:
                continue
            pricing = m.get("pricing") or {}
            in_1k, out_1k = _per_1k_from_openrouter_pricing(pricing)
            existing = (
                await db.execute(
                    select(AIModel).where(
                        AIModel.connection_id == conn.id,
                        AIModel.external_id == ext_id,
                    )
                )
            ).scalars().first()
            payload = {
                "connection_id": conn.id,
                "external_id": ext_id,
                "display_name": m.get("name") or ext_id,
                "provider_type": provider,
                "input_cost_per_1k": in_1k,
                "output_cost_per_1k": out_1k,
                "pricing_unit": "1k",
                "pricing_raw": json.dumps(m),
                "context_length": m.get("context_length"),
                "is_image_model": _guess_is_image_model(ext_id),
                "last_synced_at": datetime.utcnow(),
            }
            if existing:
                for k, v in payload.items():
                    setattr(existing, k, v)
            else:
                db.add(AIModel(**payload, is_enabled=True))
            synced += 1
    else:
        # OpenAI-compatible /v1/models — list only; pricing may require separate catalog
        base = (conn.base_url or "https://api.openai.com/v1").rstrip("/")
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.get(
                f"{base}/models",
                headers={"Authorization": f"Bearer {api_key}"},
            )
            resp.raise_for_status()
            for m in resp.json().get("data", []):
                ext_id = m.get("id")
                if not ext_id:
                    continue
                existing = (
                    await db.execute(
                        select(AIModel).where(
                            AIModel.connection_id == conn.id,
                            AIModel.external_id == ext_id,
                        )
                    )
                ).scalars().first()
                payload = {
                    "connection_id": conn.id,
                    "external_id": ext_id,
                    "display_name": ext_id,
                    "provider_type": provider,
                    "pricing_raw": json.dumps(m),
                    "is_image_model": _guess_is_image_model(ext_id),
                    "last_synced_at": datetime.utcnow(),
                }
                if existing:
                    for k, v in payload.items():
                        setattr(existing, k, v)
                else:
                    db.add(AIModel(**payload, is_enabled=True))
                synced += 1

    conn.last_sync_at = datetime.utcnow()
    await db.flush()
    return synced


async def sync_connection_with_flash(
    db: AsyncSession, conn: Connection, api_key: str
) -> dict[str, int]:
    """Sync one connection after briefly disabling all models (same as manual Sync Now)."""
    all_models = (await db.execute(select(AIModel))).scalars().all()
    for m in all_models:
        m.is_enabled = False
    await db.flush()

    synced = await sync_connection_models(db, conn, api_key)

    refreshed = (await db.execute(select(AIModel))).scalars().all()
    for m in refreshed:
        m.is_enabled = True
    await db.flush()
    return {"synced": synced, "models_refreshed": len(refreshed)}


async def disable_models_for_connection(db: AsyncSession, connection_id: int) -> int:
    """Turn off all catalog models tied to a connection (e.g. when connection is disabled)."""
    result = await db.execute(
        update(AIModel).where(AIModel.connection_id == connection_id).values(is_enabled=False)
    )
    return result.rowcount or 0


async def enable_models_for_connection(db: AsyncSession, connection_id: int) -> int:
    """Turn on all catalog models tied to a connection (e.g. when connection is re-enabled)."""
    result = await db.execute(
        update(AIModel).where(AIModel.connection_id == connection_id).values(is_enabled=True)
    )
    return result.rowcount or 0
