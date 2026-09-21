"""Sync model catalogs and provider-native pricing from connections."""

import json
import logging
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import normalize_openrouter_base_url
from app.models.connection import Connection
from app.models.model_catalog import AIModel
from app.services.model_capabilities import image_id_looks_generative
from app.services.model_tool_compatibility_service import ensure_model_compatibility_rows
from app.services.provider_http import get_provider_rest_client
from app.services.video_catalog_service import normalize_video_capabilities

logger = logging.getLogger("app.services.model_sync")


def _fresh_request_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Cache-Control": "no-cache, no-store, max-age=0",
        "Pragma": "no-cache",
    }


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


def _guess_is_video_model(ext_id: str, item: dict | None = None) -> bool:
    del ext_id
    if not isinstance(item, dict):
        return False
    arch = item.get("architecture") if isinstance(item.get("architecture"), dict) else {}
    outputs = arch.get("output_modalities") or item.get("output_modalities") or []
    if isinstance(outputs, list) and any(str(x).lower() == "video" for x in outputs):
        return True
    return bool(item.get("video_generation") or item.get("video_capabilities"))


async def fetch_openrouter_models(api_key: str, base_url: str | None) -> list[dict]:
    url = normalize_openrouter_base_url(base_url) + "/models"
    headers = _fresh_request_headers(api_key)
    client = get_provider_rest_client()
    # OpenRouter defaults this endpoint to text-output models. Request the
    # complete catalog so image/audio/video-only models are not omitted.
    resp = await client.get(
        url,
        headers=headers,
        params={"output_modalities": "all"},
    )
    resp.raise_for_status()
    payload = resp.json()
    data = payload.get("data", []) if isinstance(payload, dict) else []
    return data if isinstance(data, list) else []


async def fetch_openrouter_video_models(api_key: str, base_url: str | None) -> dict[str, dict]:
    """Map model id → OpenRouter /videos/models capability snapshot."""
    url = normalize_openrouter_base_url(base_url) + "/videos/models"
    headers = _fresh_request_headers(api_key)
    try:
        client = get_provider_rest_client()
        resp = await client.get(url, headers=headers)
        if resp.status_code >= 400:
            logger.warning(
                "OpenRouter video catalog returned HTTP %s for %s",
                resp.status_code,
                url,
            )
            return {}
        payload = resp.json()
        data = payload.get("data", []) if isinstance(payload, dict) else []
    except Exception:
        logger.warning("OpenRouter video catalog sync failed for %s", url, exc_info=True)
        return {}
    out: dict[str, dict] = {}
    if not isinstance(data, list):
        return out
    for item in data:
        if not isinstance(item, dict):
            continue
        ext_id = item.get("id") or item.get("canonical_slug")
        if not ext_id:
            continue
        # Keep both identifiers: /models commonly exposes `id`, while
        # /videos/models may expose a canonical slug for the same model.
        for key in (item.get("id"), item.get("canonical_slug")):
            if key:
                out[str(key)] = item
    return out


async def fetch_openrouter_image_models(api_key: str, base_url: str | None) -> dict[str, dict]:
    """Map model identifiers to OpenRouter /images/models snapshots."""
    url = normalize_openrouter_base_url(base_url) + "/images/models"
    headers = _fresh_request_headers(api_key)
    try:
        client = get_provider_rest_client()
        resp = await client.get(url, headers=headers)
        if resp.status_code >= 400:
            logger.warning(
                "OpenRouter image catalog returned HTTP %s for %s",
                resp.status_code,
                url,
            )
            return {}
        payload = resp.json()
        data = payload.get("data", []) if isinstance(payload, dict) else []
    except Exception:
        logger.warning("OpenRouter image catalog sync failed for %s", url, exc_info=True)
        return {}
    out: dict[str, dict] = {}
    if not isinstance(data, list):
        return out
    for item in data:
        if not isinstance(item, dict):
            continue
        for key in (item.get("id"), item.get("canonical_slug")):
            if key:
                out[str(key)] = item
    return out


async def fetch_provider_models(
    provider: str,
    api_key: str,
    base_url: str | None,
) -> list[dict]:
    """Fetch the complete model catalog for a configured provider.

    Most presets expose the OpenAI-compatible `/models` response. Native
    Google and Anthropic connections use different authentication/response
    conventions, so normalize those responses here instead of dropping them
    from the catalog.
    """
    provider = provider.lower()
    base = (base_url or "https://api.openai.com/v1").rstrip("/")
    headers = _fresh_request_headers(api_key)
    params: dict[str, str] | None = None

    if provider in {"google", "gemini", "google-ai-studio", "google-gemini"}:
        headers = {
            "Cache-Control": "no-cache, no-store, max-age=0",
            "Pragma": "no-cache",
        }
        params = {"key": api_key}
    elif provider == "anthropic":
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "Cache-Control": "no-cache, no-store, max-age=0",
            "Pragma": "no-cache",
        }
    elif provider in {"azure", "azure-openai"}:
        headers = {
            "api-key": api_key,
            "Cache-Control": "no-cache, no-store, max-age=0",
            "Pragma": "no-cache",
        }

    client = get_provider_rest_client()
    resp = await client.get(f"{base}/models", headers=headers, params=params)
    resp.raise_for_status()
    payload = resp.json()

    if not isinstance(payload, dict):
        return []
    raw_items = payload.get("data")
    if not isinstance(raw_items, list):
        raw_items = payload.get("models")
    if not isinstance(raw_items, list):
        return []

    normalized: list[dict] = []
    for item in raw_items:
        if isinstance(item, str):
            item = {"id": item}
        if not isinstance(item, dict):
            continue
        model = dict(item)
        model_id = model.get("id") or model.get("name")
        if not model_id:
            continue
        model_id = str(model_id)
        if model_id.startswith("models/"):
            model_id = model_id.removeprefix("models/")
        model["id"] = model_id
        normalized.append(model)
    return normalized


def _openrouter_snapshot(
    model: dict,
    video_meta: dict | None,
    image_meta: dict | None = None,
) -> dict:
    """Build the catalog snapshot with the provider's authoritative modalities."""
    snapshot = dict(model)
    if video_meta:
        model_id = str(model.get("id") or video_meta.get("id") or "")
        snapshot["video_generation"] = video_meta
        snapshot["video_capabilities"] = normalize_video_capabilities(
            provider_type="openrouter",
            model_id=model_id,
            raw={**model, "video_generation": video_meta},
        )
    else:
        snapshot.pop("video_generation", None)
        snapshot.pop("video_capabilities", None)

    if image_meta:
        image_architecture = image_meta.get("architecture")
        if isinstance(image_architecture, dict):
            snapshot["architecture"] = image_architecture
        snapshot["image_generation"] = image_meta
    else:
        snapshot.pop("image_generation", None)

    # OpenRouter's general catalog can advertise media output for models that
    # are not available through its dedicated generation APIs. The specialized
    # catalogs are authoritative for both Video and Image generation.
    architecture = snapshot.get("architecture")
    if isinstance(architecture, dict):
        outputs = architecture.get("output_modalities")
        if isinstance(outputs, list):
            allowed_outputs = {str(value).lower() for value in outputs if str(value).lower() not in {"video", "image"}}
            if video_meta:
                allowed_outputs.add("video")
            if image_meta:
                allowed_outputs.add("image")
            snapshot["architecture"] = {
                **architecture,
                "output_modalities": [value for value in outputs if str(value).lower() in allowed_outputs],
            }
    return snapshot


async def set_model_admin_enabled(db: AsyncSession, model: AIModel, enabled: bool) -> None:
    """Apply sticky admin enable/disable for a catalog model.

    OFF locks the model (`admin_disabled`) so sync / connection enable cannot turn it on.
    ON clears the lock and sets `is_enabled` only when the parent connection is active.

    A model the provider has just added arrives locked (see
    ``_upsert_catalog_model``), so ON here is also the approval action that puts
    a new model into service for the first time.
    """
    if not enabled:
        model.admin_disabled = True
        model.is_enabled = False
        return

    model.admin_disabled = False
    conn = None
    if model.connection_id is not None:
        conn = await db.get(Connection, model.connection_id)
    model.is_enabled = bool(conn.is_active) if conn is not None else False


def _upsert_catalog_model(db: AsyncSession, existing: AIModel | None, payload: dict) -> None:
    """Update an existing catalog row, or insert a new model switched off.

    A model nobody has approved is not in service. Providers add to their
    catalogs whenever they like -- OpenRouter alone gains models weekly -- and
    with the previous behaviour each one became selectable by every user the
    moment a sync noticed it: unknown cost, unknown behaviour, no owner inside
    the organization, live without anyone having decided so.

    So a new row is inserted `is_enabled=False` and `admin_disabled=True`. The
    lock is what makes it hold: `is_enabled=False` on its own would be undone
    the next time the connection is toggled off and on, because
    ``enable_models_for_connection`` switches on everything that is not locked.
    Turning the model ON in the admin UI clears the lock and puts it in service
    -- that single action is the approval.

    Existing rows keep whatever state they have; a sync never changes
    `is_enabled` or `admin_disabled` on a model that is already known.
    """
    if existing:
        for key, value in payload.items():
            setattr(existing, key, value)
        return
    db.add(
        AIModel(
            **payload,
            is_enabled=False,
            admin_disabled=True,
            first_seen_at=payload.get("last_synced_at") or datetime.utcnow(),
        )
    )


async def sync_connection_models(db: AsyncSession, conn: Connection, api_key: str) -> int:
    """Upsert models for a connection; pricing copied verbatim from provider response.

    Existing rows keep `is_enabled` / `admin_disabled`. New models arrive off and
    locked, waiting for an administrator to approve them -- see
    ``_upsert_catalog_model``.
    """
    provider = conn.provider_type.lower()
    synced = 0

    if provider == "openrouter":
        items = await fetch_openrouter_models(api_key, conn.base_url)
        video_models = await fetch_openrouter_video_models(api_key, conn.base_url)
        image_models = await fetch_openrouter_image_models(api_key, conn.base_url)
        seen_ids: set[str] = set()
        for m in items:
            ext_id = m.get("id")
            if not ext_id:
                continue
            seen_ids.add(str(ext_id))
            if m.get("canonical_slug"):
                seen_ids.add(str(m["canonical_slug"]))
            pricing = m.get("pricing") or {}
            in_1k, out_1k = _per_1k_from_openrouter_pricing(pricing)
            existing = (
                (
                    await db.execute(
                        select(AIModel).where(
                            AIModel.connection_id == conn.id,
                            AIModel.external_id == ext_id,
                        )
                    )
                )
                .scalars()
                .first()
            )
            video_meta = video_models.get(str(ext_id))
            image_meta = image_models.get(str(ext_id))
            snapshot = _openrouter_snapshot(m, video_meta, image_meta)
            video_meta = video_models.get(ext_id)
            payload = {
                "connection_id": conn.id,
                "external_id": ext_id,
                "display_name": m.get("name") or ext_id,
                "provider_type": provider,
                "input_cost_per_1k": in_1k,
                "output_cost_per_1k": out_1k,
                "pricing_unit": "1k",
                "pricing_raw": json.dumps(snapshot),
                "context_length": m.get("context_length"),
                "is_image_model": bool(image_meta),
                "is_video_model": bool(video_meta),
                "last_synced_at": datetime.utcnow(),
            }
            _upsert_catalog_model(db, existing, payload)
            synced += 1

        # Upsert video-only catalog entries that appear on /videos/models but not /models.
        video_only_seen: set[str] = set()
        for lookup_id, video_meta in video_models.items():
            canonical_id = str(video_meta.get("id") or video_meta.get("canonical_slug") or lookup_id)
            aliases = {
                str(value)
                for value in (
                    video_meta.get("id"),
                    video_meta.get("canonical_slug"),
                    lookup_id,
                )
                if value
            }
            if aliases & seen_ids or canonical_id in video_only_seen:
                continue
            video_only_seen.update(aliases)
            ext_id = canonical_id
            existing = (
                (
                    await db.execute(
                        select(AIModel).where(
                            AIModel.connection_id == conn.id,
                            AIModel.external_id == ext_id,
                        )
                    )
                )
                .scalars()
                .first()
            )
            snapshot = {
                "id": ext_id,
                "name": video_meta.get("name") or ext_id,
                "architecture": {
                    "input_modalities": ["text", "image"] if video_meta.get("supported_frame_images") else ["text"],
                    "output_modalities": ["video"],
                },
                "video_generation": video_meta,
            }
            snapshot["video_capabilities"] = normalize_video_capabilities(
                provider_type=provider,
                model_id=ext_id,
                raw=snapshot,
            )
            pricing = video_meta.get("pricing") or video_meta.get("pricing_skus") or {}
            in_1k, out_1k = _per_1k_from_openrouter_pricing(pricing)
            video_only_payload = {
                "connection_id": conn.id,
                "external_id": ext_id,
                "display_name": video_meta.get("name") or ext_id,
                "provider_type": provider,
                "input_cost_per_1k": in_1k,
                "output_cost_per_1k": out_1k,
                "pricing_unit": "1k",
                "pricing_raw": json.dumps(snapshot),
                "context_length": video_meta.get("context_length"),
                "is_image_model": False,
                "is_video_model": True,
                "last_synced_at": datetime.utcnow(),
            }
            _upsert_catalog_model(db, existing, video_only_payload)
            synced += 1

        # A fresh provider catalog is authoritative. Models that disappeared
        # from the full response must not remain selectable from a previous
        # sync, while their rows are retained for audit/history.
        if seen_ids:
            await db.execute(
                update(AIModel)
                .where(
                    AIModel.connection_id == conn.id,
                    AIModel.external_id.not_in(seen_ids),
                )
                .values(is_enabled=False)
            )
    else:
        items = await fetch_provider_models(provider, api_key, conn.base_url)
        for m in items:
            ext_id = m.get("id")
            if not ext_id:
                continue
            existing = (
                (
                    await db.execute(
                        select(AIModel).where(
                            AIModel.connection_id == conn.id,
                            AIModel.external_id == ext_id,
                        )
                    )
                )
                .scalars()
                .first()
            )
            payload = {
                "connection_id": conn.id,
                "external_id": ext_id,
                "display_name": m.get("display_name") or m.get("name") or ext_id,
                "provider_type": provider,
                "pricing_raw": json.dumps(m),
                # Only a guess, and only because this provider published no
                # modality metadata; the read path re-derives the answer from
                # the stored snapshot and prefers whatever the provider said.
                "is_image_model": image_id_looks_generative(ext_id),
                "is_video_model": _guess_is_video_model(ext_id, m if isinstance(m, dict) else None),
                "last_synced_at": datetime.utcnow(),
            }
            _upsert_catalog_model(db, existing, payload)
            synced += 1

    conn.last_sync_at = datetime.utcnow()
    await db.flush()
    synced_models = (await db.execute(select(AIModel).where(AIModel.connection_id == conn.id))).scalars().all()
    await ensure_model_compatibility_rows(db, synced_models)
    return synced


async def sync_connection_with_flash(db: AsyncSession, conn: Connection, api_key: str) -> dict[str, int]:
    """Sync one connection's catalog without flipping enable state on any models.

    Historically this briefly disabled then re-enabled the entire catalog (all
    connections), which resurrected admin-disabled models and models on other
    connections. Flash UX is client-side only now.
    """
    synced = await sync_connection_models(db, conn, api_key)
    return {"synced": synced, "models_refreshed": synced}


async def disable_models_for_connection(db: AsyncSession, connection_id: int) -> int:
    """Turn off all catalog models tied to a connection (e.g. when connection is disabled)."""
    result = await db.execute(update(AIModel).where(AIModel.connection_id == connection_id).values(is_enabled=False))
    return result.rowcount or 0


async def enable_models_for_connection(db: AsyncSession, connection_id: int) -> int:
    """Turn on catalog models for a connection, skipping sticky admin-disabled rows."""
    result = await db.execute(
        update(AIModel)
        .where(
            AIModel.connection_id == connection_id,
            AIModel.admin_disabled == False,  # noqa: E712
        )
        .values(is_enabled=True)
    )
    return result.rowcount or 0
