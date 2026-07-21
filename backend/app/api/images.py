"""Image generation (independent of Open WebUI) — OpenAI-compatible images API."""

from __future__ import annotations

import asyncio
import base64
import re
import time
from urllib.parse import urlparse

import httpx
import litellm
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_active_user
from app.database import AsyncSessionLocal, get_db
from app.models.connection import Connection
from app.models.media import MediaAsset
from app.models.model_catalog import AIModel
from app.models.user import User
from app.services.secret_crypto import decrypt_secret
from app.services.image_model_resolver import (
    is_image_model_failover_error,
    list_auto_router_image_candidates,
)
from app.services.budget_reservation_service import (
    estimate_image_hold,
    release,
    reservation_key,
    reserve,
)
from app.config import get_settings
from app.services.media_authorization_service import MediaAccessAction, load_authorized_media_asset
from app.services.openrouter_image_service import (
    OPENROUTER_EMPTY_IMAGE_RETRY_DELAYS_SEC,
    OPENROUTER_FALLBACK_TIMEOUT,
    build_fast_openrouter_payload,
    build_openrouter_headers,
    gemini_image_size_for_model,
    is_openai_gpt_image_model,
    is_openrouter_auto_model,
    is_retryable_openrouter_transport_error,
    is_transient_empty_openrouter_image_response,
    openrouter_image_modalities,
    optimize_openrouter_image_model,
    post_openrouter_json,
    prefer_openrouter_images_generations,
)
from app.services.storage_service import (
    media_input_limit,
    media_content_hash,
    media_public_url,
    read_media_bytes,
    resolve_media_blob,
    store_media_from_blob,
)
from app.services.user_chat_storage_service import finalize_chat_session_image
from app.services.image_billing_service import ImageBillingCapture, log_image_usage
from app.services.llm_providers import litellm_model_for_provider, resolve_litellm_provider

router = APIRouter(prefix="/api/images", tags=["images"])
_alpha_router_MEDIA_PATH = re.compile(r"/api/chat/media/(\d+)/file/?(?:\?.*)?$")


def parse_alpha_router_media_asset_id(reference: str) -> int | None:
    """Extract media asset id from Alpha Router /api/chat/media/{id}/file URLs."""
    ref = (reference or "").strip()
    if not ref:
        return None
    path = urlparse(ref).path if ref.startswith(("http://", "https://")) else ref.split("?")[0]
    match = _alpha_router_MEDIA_PATH.search(path)
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


async def resolve_reference_image_for_upstream(
    db: AsyncSession,
    user: User,
    reference_image: str | None,
) -> str | None:
    """Turn Alpha Router media paths into data URLs OpenRouter and other providers can consume."""
    ref = (reference_image or "").strip()
    if not ref:
        return None
    if ref.startswith("data:"):
        try:
            from app.services.bounded_io import decode_data_url_bounded
            from app.services.image_decode_policy import image_dimensions

            data, mime = decode_data_url_bounded(
                ref,
                max_decoded_bytes=media_input_limit(),
            )
            if not mime.lower().startswith("image/"):
                raise ValueError("Reference data URL must be an image")
            await asyncio.to_thread(image_dimensions, data)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"

    asset_id = parse_alpha_router_media_asset_id(ref)
    if asset_id is not None:
        row = await load_authorized_media_asset(
            db,
            user,
            asset_id,
            action=MediaAccessAction.READ,
            not_found_detail="Reference image not found",
        )
        try:
            data = await read_media_bytes(row)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Reference image file not found") from exc
        mime = (row.mime_type or "image/png").split(";")[0].strip() or "image/png"
        try:
            from app.services.image_decode_policy import image_dimensions

            await asyncio.to_thread(image_dimensions, data)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Reference image is invalid or unsafe") from exc
        encoded = base64.b64encode(data).decode("ascii")
        return f"data:{mime};base64,{encoded}"

    if ref.startswith("http://") or ref.startswith("https://"):
        try:
            data, mime = await resolve_media_blob(source_url=ref)
            from app.services.image_decode_policy import image_dimensions

            await asyncio.to_thread(image_dimensions, data)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail="Reference image fetch failed") from exc
        return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"

    raise HTTPException(status_code=400, detail=f"Invalid reference image URL: {ref[:160]}")


def _normalize_model_id(model_id: str) -> str:
    raw = (model_id or "").strip()
    while raw.startswith("~"):
        raw = raw[1:]
    return raw


def _normalize_openrouter_base(base_url: str | None) -> str:
    base = (base_url or "https://openrouter.ai/api/v1").strip().rstrip("/")
    if not base:
        return "https://openrouter.ai/api/v1"
    low = base.lower()
    # Admins often save https://openrouter.ai; force API root to avoid HTML pages.
    if "openrouter.ai" in low and "/api/" not in low:
        return "https://openrouter.ai/api/v1"
    return base


class ImageRequest(BaseModel):
    model: str
    prompt: str
    n: int = 1
    size: str = "1024x1024"
    aspect_ratio: str | None = None
    operation: str = "generation"  # generation | img2img | imagine | outpaint
    reference_image: str | None = None  # data URL or http(s) URL for image-to-image
    chat_session_id: str | None = None
    persist: bool = True
    image_size_tier: str | None = None
    routing: dict[str, object] | None = None


def _is_openrouter_chat_image_model(model_id: str) -> bool:
    if is_openrouter_auto_model(model_id):
        return True
    low = (model_id or "").lower()
    return any(
        h in low
        for h in (
            "image",
            "banana",
            "dall-e",
            "dalle",
            "flux",
            "sdxl",
            "stable-diffusion",
        )
    )


def _openrouter_modalities(model_id: str) -> list[str]:
    return openrouter_image_modalities(model_id)


def _prefer_openrouter_images_generations(model_id: str) -> bool:
    return prefer_openrouter_images_generations(model_id)


def _normalize_image_size(size: str) -> str:
    """Validate WxH dimensions (256–2048 per side, rounded to multiples of 8)."""
    raw = (size or "").strip().lower()
    match = re.fullmatch(r"(\d+)\s*x\s*(\d+)", raw)
    if not match:
        return "1024x1024"
    w = int(match.group(1))
    h = int(match.group(2))
    if w <= 0 or h <= 0:
        return "1024x1024"
    w = max(256, min(2048, round(w / 8) * 8))
    h = max(256, min(2048, round(h / 8) * 8))
    return f"{w}x{h}"


_OPENROUTER_ASPECT_RATIOS: tuple[tuple[str, float], ...] = (
    ("1:1", 1.0),
    ("2:3", 2 / 3),
    ("3:2", 3 / 2),
    ("3:4", 3 / 4),
    ("4:3", 4 / 3),
    ("4:5", 4 / 5),
    ("5:4", 5 / 4),
    ("9:16", 9 / 16),
    ("16:9", 16 / 9),
    ("21:9", 21 / 9),
)


_OPENROUTER_ASPECT_RATIO_LABELS: frozenset[str] = frozenset(label for label, _ in _OPENROUTER_ASPECT_RATIOS)

_ASPECT_RATIO_TO_DEFAULT_SIZE: dict[str, str] = {
    "1:1": "1024x1024",
    "16:9": "1344x768",
    "9:16": "768x1344",
    "3:2": "1248x832",
    "2:3": "832x1248",
    "4:3": "1184x888",
    "3:4": "888x1184",
    "4:5": "896x1120",
    "5:4": "1120x896",
    "21:9": "1536x656",
}


def _normalize_aspect_ratio(raw: str | None) -> str | None:
    """Validate W:H against OpenRouter-supported aspect_ratio labels."""
    text = (raw or "").strip().replace(" ", "")
    match = re.fullmatch(r"(\d+):(\d+)", text)
    if not match:
        return None
    w = int(match.group(1))
    h = int(match.group(2))
    if w <= 0 or h <= 0:
        return None

    def _gcd(a: int, b: int) -> int:
        while b:
            a, b = b, a % b
        return a or 1

    simplified = f"{w // _gcd(w, h)}:{h // _gcd(w, h)}"
    if simplified in _OPENROUTER_ASPECT_RATIO_LABELS:
        return simplified
    ratio = w / h
    best = "1:1"
    best_diff = float("inf")
    for label, target in _OPENROUTER_ASPECT_RATIOS:
        diff = abs(ratio - target)
        if diff < best_diff:
            best_diff = diff
            best = label
    return best


def _aspect_ratio_to_default_size(aspect_ratio: str) -> str:
    normalized = _normalize_aspect_ratio(aspect_ratio) or "1:1"
    return _normalize_image_size(_ASPECT_RATIO_TO_DEFAULT_SIZE.get(normalized, "1024x1024"))


def _reference_image_bytes(reference_image: str) -> bytes | None:
    ref = (reference_image or "").strip()
    if not ref.startswith("data:"):
        return None
    try:
        from app.services.bounded_io import decode_data_url_bounded

        data, _mime = decode_data_url_bounded(
            ref,
            max_decoded_bytes=media_input_limit(),
        )
        return data
    except ValueError:
        return None


async def _reference_image_dimensions(reference_image: str) -> tuple[int, int] | None:
    ref = (reference_image or "").strip()
    data = _reference_image_bytes(ref)
    if data is None and (ref.startswith("http://") or ref.startswith("https://")):
        try:
            from app.services.bounded_io import bounded_get_bytes
            from app.services.ssrf_guard import safe_client

            async with safe_client() as client:
                data, _mime = await bounded_get_bytes(
                    client,
                    ref,
                    max_bytes=media_input_limit(),
                )
        except Exception:
            return None
    if not data:
        return None
    try:
        from app.services.image_decode_policy import image_dimensions

        return await asyncio.to_thread(image_dimensions, data)
    except Exception:
        return None
    return None


async def _resolve_generation_dimensions(
    *,
    reference_image: str | None,
    aspect_ratio: str | None,
    size: str,
) -> tuple[str, str]:
    """Return (aspect_ratio_label, normalized WxH) for upstream providers."""
    if reference_image:
        dims = await _reference_image_dimensions(reference_image)
        if dims:
            normalized = _normalize_image_size(f"{dims[0]}x{dims[1]}")
            return _map_size_to_aspect_ratio(normalized), normalized

    normalized_ar = _normalize_aspect_ratio(aspect_ratio)
    if normalized_ar:
        return normalized_ar, _aspect_ratio_to_default_size(normalized_ar)

    normalized_size = _normalize_image_size(size)
    return _map_size_to_aspect_ratio(normalized_size), normalized_size


def _map_size_to_aspect_ratio(size: str) -> str:
    """Map WxH to nearest OpenRouter-supported aspect_ratio label."""
    size_to_aspect_ratio = {
        "256x256": "1:1",
        "512x512": "1:1",
        "1024x1024": "1:1",
        "1344x768": "16:9",
        "768x1344": "9:16",
        "1248x832": "3:2",
        "832x1248": "2:3",
        # Legacy preset sizes
        "1536x1024": "3:2",
        "1792x1024": "16:9",
        "1024x1536": "2:3",
        "1024x1792": "9:16",
        "auto": "1:1",
    }
    normalized = _normalize_image_size(size)
    if normalized in size_to_aspect_ratio:
        return size_to_aspect_ratio[normalized]
    match = re.fullmatch(r"(\d+)x(\d+)", normalized)
    if not match:
        return "1:1"
    w = int(match.group(1))
    h = int(match.group(2))
    ratio = w / h
    best = "1:1"
    best_diff = float("inf")
    for label, target in _OPENROUTER_ASPECT_RATIOS:
        diff = abs(ratio - target)
        if diff < best_diff:
            best_diff = diff
            best = label
    return best


def _coalesce_image_item(*, url: str | None = None, b64: str | None = None) -> dict | None:
    """Prefer a single payload per image; b64_json wins when both are present."""
    b = (b64 or "").strip()
    if b:
        return {"b64_json": b}
    u = (url or "").strip()
    if u:
        return {"url": u}
    return None


def _dedupe_image_items(items: list[dict]) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for item in items:
        key = (item.get("b64_json") or item.get("url") or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


async def _blob_from_image_item(item: dict) -> tuple[bytes, str] | None:
    url = item.get("url") if isinstance(item.get("url"), str) else None
    b64 = item.get("b64_json") if isinstance(item.get("b64_json"), str) else None
    data_url: str | None = None
    source_url: str | None = None
    if b64 and b64.strip():
        data_url = f"data:image/png;base64,{b64.strip()}"
    elif url and url.strip():
        u = url.strip()
        if u.startswith("data:image/"):
            data_url = u
        elif u.startswith("http"):
            source_url = u
    if not data_url and not source_url:
        return None
    try:
        return await resolve_media_blob(data_url=data_url, source_url=source_url)
    except Exception:
        return None


async def _persist_image_data_items(
    db: AsyncSession,
    *,
    user: User,
    items: list[dict],
    model: str,
    prompt: str,
    chat_session_id: str | None,
    max_items: int = 1,
) -> list[dict]:
    out: list[dict] = []
    seen_hashes: set[str] = set()
    for item in _dedupe_image_items(items):
        blob_mime = await _blob_from_image_item(item)
        if not blob_mime:
            continue
        blob, mime = blob_mime
        blob, mime, content_hash = await asyncio.to_thread(
            media_content_hash,
            blob,
            mime,
            "image",
        )
        if content_hash in seen_hashes:
            continue
        seen_hashes.add(content_hash)
        if max_items > 0 and len(out) >= max_items:
            break

        asset = await store_media_from_blob(
            db,
            user_id=user.id,
            username=user.username,
            kind="image",
            blob=blob,
            mime=mime,
            content_hash=content_hash,
            source_model=model,
            source_prompt=prompt,
            chat_session_id=chat_session_id,
        )
        out.append({"url": media_public_url(asset.id)})
    return out


async def _finalize_image_response(
    db: AsyncSession,
    user: User,
    body: ImageRequest,
    items: list[dict],
    *,
    aspect_ratio: str | None = None,
    routing: dict[str, object] | None = None,
) -> dict:
    if body.persist and items:
        items = await _persist_image_data_items(
            db,
            user=user,
            items=items,
            model=body.model,
            prompt=body.prompt,
            chat_session_id=body.chat_session_id,
            max_items=max(1, min(4, int(body.n or 1))),
        )
        if body.chat_session_id and items:
            url = items[0].get("url") if isinstance(items[0], dict) else None
            if isinstance(url, str) and url.strip():
                await finalize_chat_session_image(
                    db,
                    user.id,
                    body.chat_session_id,
                    url.strip(),
                    body.prompt,
                    body.model,
                    routing,
                )
    result: dict = {"data": items}
    if body.size:
        result["size"] = body.size
    if aspect_ratio:
        result["aspect_ratio"] = aspect_ratio
    if body.image_size_tier:
        result["image_size_tier"] = body.image_size_tier
    result["model"] = body.model
    if routing:
        result["routing"] = routing
    return result


async def _close_image_request_transaction(
    db: AsyncSession,
    *,
    success: bool,
) -> None:
    """Release request-owned row locks before independent budget settlement."""
    if success:
        await db.commit()
    else:
        await db.rollback()


def _extract_image_url_and_b64(obj: dict) -> tuple[str | None, str | None]:
    """Pull url/b64 from snake_case, camelCase, and nested OpenRouter/Gemini shapes."""
    image_url_field = obj.get("image_url") or obj.get("imageUrl") or obj.get("image")
    url_val: str | None = None
    if isinstance(image_url_field, str):
        url_val = image_url_field
    elif isinstance(image_url_field, dict):
        url_val = (
            image_url_field.get("url")
            or image_url_field.get("uri")
            or image_url_field.get("data")
        )
    url_val = url_val or obj.get("url") or obj.get("uri")
    inline = obj.get("inline_data") or obj.get("inlineData")
    b64_val = (
        obj.get("b64_json")
        or obj.get("b64Json")
        or obj.get("image_base64")
        or obj.get("imageBase64")
    )
    if not b64_val and isinstance(inline, dict):
        b64_val = inline.get("data") or inline.get("b64_json")
        mime = str(inline.get("mime_type") or inline.get("mimeType") or "image/png")
        if b64_val and not str(b64_val).startswith("data:"):
            url_val = url_val or f"data:{mime};base64,{b64_val}"
            b64_val = None
    return (
        str(url_val) if url_val else None,
        str(b64_val) if b64_val else None,
    )


def _collect_openrouter_images(data: dict) -> list[dict]:
    """
    OpenRouter image-capable models can return image payloads in different shapes.
    Normalize the common variants to: [{"url": ...}] or [{"b64_json": ...}].
    """
    out: list[dict] = []

    def add_image(*, url: str | None = None, b64: str | None = None):
        item = _coalesce_image_item(url=url, b64=b64)
        if item:
            out.append(item)

    def extract_from_text(text: str | None):
        if not isinstance(text, str) or not text.strip():
            return
        # Some providers return markdown image links instead of structured fields.
        for url in re.findall(r"!\[[^\]]*\]\((https?://[^\s)]+)\)", text, flags=re.IGNORECASE):
            add_image(url=url)
        for url in re.findall(r"(https?://[^\s\"')]+)", text, flags=re.IGNORECASE):
            if any(ext in url.lower() for ext in (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")):
                add_image(url=url)
        # Sometimes base64 data URL is embedded directly in text.
        for data_url in re.findall(r"(data:image/[a-zA-Z0-9.+-]+;base64,[A-Za-z0-9+/=\s]+)", text):
            cleaned = data_url.replace("\n", "").replace("\r", "").replace(" ", "")
            if cleaned.startswith("data:image/"):
                add_image(url=cleaned)

    choices = data.get("choices") or []
    for choice in choices:
        msg = (choice or {}).get("message") or {}
        before = len(out)
        structured_images = msg.get("images") or []

        if structured_images:
            for img in structured_images:
                if not isinstance(img, dict):
                    continue
                url_val, b64_val = _extract_image_url_and_b64(img)
                add_image(url=url_val, b64=b64_val)
            # Only skip other variants when structured images actually yielded bytes.
            if len(out) > before:
                continue

        # Variant B: message.image_url / message.url / message.b64_json
        url_val, b64_val = _extract_image_url_and_b64(msg)
        add_image(url=url_val, b64=b64_val)

        # Variant C: message.content as list of multimodal parts
        content = msg.get("content")
        if isinstance(content, list):
            for part in content:
                if not isinstance(part, dict):
                    continue
                ptype = str(part.get("type") or "").lower()
                part_url, part_b64 = _extract_image_url_and_b64(part)
                if ptype in {"output_image", "image", "image_url", "inline_data"}:
                    part_url = part_url or (
                        str(part.get("data")) if part.get("data") else None
                    )
                add_image(url=part_url, b64=part_b64)
                if isinstance(part.get("text"), str):
                    extract_from_text(part.get("text"))
        elif isinstance(content, str):
            extract_from_text(content)

        # Variant D: top-level/message-level metadata blobs sometimes carry image URLs.
        if isinstance(choice, dict):
            url_val, b64_val = _extract_image_url_and_b64(choice)
            add_image(url=url_val, b64=b64_val)

    # Variant E: top-level data[] when choices did not already yield images.
    if not out:
        for item in data.get("data") or []:
            if not isinstance(item, dict):
                continue
            url_val, b64_val = _extract_image_url_and_b64(item)
            add_image(url=url_val, b64=b64_val)

    return _dedupe_image_items(out)


def _collect_standard_image_payload(data: dict) -> list[dict]:
    """Collect image payloads from OpenAI-compatible /images responses."""
    out: list[dict] = []
    for item in data.get("data") or []:
        if not isinstance(item, dict):
            continue
        coalesced = _coalesce_image_item(url=item.get("url"), b64=item.get("b64_json"))
        if coalesced:
            out.append(coalesced)
    return out


def _collect_litellm_image_items(response: object) -> list[dict]:
    if isinstance(response, dict):
        return _collect_standard_image_payload(response)
    data = getattr(response, "data", None)
    if not data:
        return []
    out: list[dict] = []
    for item in data:
        url = getattr(item, "url", None)
        b64 = getattr(item, "b64_json", None)
        if isinstance(item, dict):
            url = url or item.get("url")
            b64 = b64 or item.get("b64_json")
        coalesced = _coalesce_image_item(url=url, b64=b64)
        if coalesced:
            out.append(coalesced)
    return out


async def _resolve_image_model(
    db: AsyncSession, raw_model: str
) -> tuple[str, str | None, str | None, str | None, AIModel | None]:
    model_id = _normalize_model_id(raw_model)
    row: AIModel | None = None
    if model_id.startswith("model::"):
        try:
            model_pk = int(model_id.split("::", 1)[1])
        except Exception:
            model_pk = None
        if model_pk is not None:
            row = (
                await db.execute(
                    select(AIModel).where(AIModel.id == model_pk, AIModel.is_enabled == True)  # noqa: E712
                )
            ).scalars().first()
        if row:
            conn = await db.get(Connection, row.connection_id)
            if conn and conn.is_active:
                return row.external_id, decrypt_secret(conn.api_key_encrypted), conn.base_url, conn.provider_type, row
            row = None

    if not row:
        # external_id can exist in multiple connections; prefer latest model bound to an active connection.
        candidate = (
            await db.execute(
                select(AIModel, Connection)
                .join(Connection, Connection.id == AIModel.connection_id)
                .where(
                    AIModel.external_id == model_id,
                    AIModel.is_enabled == True,  # noqa: E712
                    Connection.is_active == True,  # noqa: E712
                )
                .order_by(AIModel.id.desc())
            )
        ).first()
        if candidate:
            row, conn = candidate
            return row.external_id, decrypt_secret(conn.api_key_encrypted), conn.base_url, conn.provider_type, row

    if not row:
        return model_id, None, None, None, None
    return model_id, None, None, None, None


@router.post("/generate")
async def generate_image(
    request: Request,
    body: ImageRequest,
    user: User = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
):
    generation_start = time.perf_counter()
    billing = ImageBillingCapture(model_id=_normalize_model_id(body.model))
    budget_reservation_id: str | None = None
    routing_reason: dict[str, object] | None = body.routing
    success = True
    error_message: str | None = None

    requested_model = _normalize_model_id(body.model)
    auto_router_requested = is_openrouter_auto_model(requested_model)
    resolve_task = asyncio.create_task(_resolve_image_model(db, body.model))

    try:
        model_id, api_key, base_url, provider_type, ai_model = await resolve_task
        billing.model_id = model_id
        billing.ai_model = ai_model
        billing.provider_type = provider_type

        auto_candidates = []
        if is_openrouter_auto_model(model_id) or auto_router_requested:
            auto_candidates = await list_auto_router_image_candidates(
                db,
                connection_id=ai_model.connection_id if ai_model else None,
                limit=3,
            )
            if not auto_candidates:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "Auto Router cannot generate images directly. "
                        "Enable at least one image-capable model on this connection in Admin → Models."
                    ),
                )
            picked = auto_candidates[0]
            model_id, ai_model, conn = picked.external_id, picked.model, picked.connection
            routing_reason = {
                **picked.reason,
                "selected_model": picked.external_id,
                "score": picked.score,
                "requested_model": requested_model,
                "candidate_models": [c.external_id for c in auto_candidates],
            }
            api_key = decrypt_secret(conn.api_key_encrypted)
            base_url = conn.base_url
            provider_type = conn.provider_type
            billing.model_id = model_id
            billing.ai_model = ai_model
            billing.provider_type = provider_type
        body.model = model_id

        hold_body = body.model_dump()
        if request.headers.get("Idempotency-Key"):
            hold_body["_idempotency_key"] = request.headers["Idempotency-Key"]
        hold = await reserve(
            db,
            user_id=user.id,
            alpha_router_api_key_id=None,
            amount_usd=estimate_image_hold(ai_model),
            operation="image",
            model_id=model_id,
            idempotency_key=reservation_key(hold_body, operation="image"),
        )
        budget_reservation_id = hold.id if hold else None
        await db.commit()

        reference_image = await resolve_reference_image_for_upstream(db, user, body.reference_image)
        resolved_aspect, body.size = await _resolve_generation_dimensions(
            reference_image=reference_image,
            aspect_ratio=body.aspect_ratio,
            size=body.size,
        )

        async def _attempt_one_model(
            *,
            attempt_model_id: str,
            attempt_api_key: str | None,
            attempt_base_url: str | None,
            attempt_provider_type: str | None,
            attempt_ai_model,
            attempt_routing: dict[str, object] | None,
        ):
            nonlocal model_id, api_key, base_url, provider_type, ai_model, routing_reason
            model_id = attempt_model_id
            api_key = attempt_api_key
            base_url = attempt_base_url
            provider_type = attempt_provider_type
            ai_model = attempt_ai_model
            routing_reason = attempt_routing
            body.model = model_id
            billing.model_id = model_id
            billing.ai_model = ai_model
            billing.provider_type = provider_type
            provider = (provider_type or "").lower()
            provider_model = litellm_model_for_provider(model_id, provider_type)
            kwargs = {
                "model": provider_model,
                "prompt": body.prompt,
                "n": body.n,
                "size": body.size,
            }
            if api_key:
                kwargs["api_key"] = api_key
            if base_url:
                kwargs["base_url"] = base_url
            llm_provider = resolve_litellm_provider(provider_type)
            if llm_provider:
                kwargs["custom_llm_provider"] = llm_provider
            kwargs["timeout"] = 180

            settings = get_settings()

            # OpenRouter image models (e.g. Gemini image) use chat/completions with modalities.
            if provider == "openrouter":
                if not api_key:
                    raise HTTPException(status_code=400, detail="OpenRouter connection has no API key")
                openrouter_base = _normalize_openrouter_base(base_url)
                kwargs["base_url"] = openrouter_base
                headers = build_openrouter_headers(api_key, referer=settings.frontend_url)
                chat_image_model = _is_openrouter_chat_image_model(model_id)
                if reference_image and body.operation not in ("img2img", "imagine", "outpaint"):
                    body.operation = "img2img"

                async def _try_openrouter_images_generations() -> tuple[list[dict] | None, dict | None]:
                    img_payload = {
                        "model": optimize_openrouter_image_model(model_id),
                        "prompt": body.prompt,
                        "n": max(1, min(4, int(body.n or 1))),
                        "size": body.size,
                        "response_format": "b64_json",
                    }
                    img_resp = await post_openrouter_json(
                        f"{openrouter_base}/images/generations",
                        headers=headers,
                        json_payload=img_payload,
                        read_timeout=OPENROUTER_FALLBACK_TIMEOUT,
                    )
                    if img_resp.status_code >= 400:
                        return None, None
                    img_data = img_resp.json()
                    items = _collect_standard_image_payload(img_data) or None
                    return items, img_data if isinstance(img_data, dict) else None

                if _prefer_openrouter_images_generations(model_id) and not reference_image:
                    out_gen, usage_data = await _try_openrouter_images_generations()
                    if usage_data:
                        billing.usage_source = usage_data
                    if out_gen:
                        return await _finalize_image_response(
                            db, user, body, out_gen, aspect_ratio=resolved_aspect,
                            routing=routing_reason,
                        )

                modalities = _openrouter_modalities(model_id)
                allow_fallbacks = not is_openai_gpt_image_model(model_id)
                safe_1k_size = _aspect_ratio_to_default_size(resolved_aspect)

                async def _try_openrouter_chat_completion(
                    *,
                    pixel_size: str,
                    mods: list[str],
                    fallbacks: bool,
                    tier: str | None = None,
                    provider_sort: str | None = None,
                    apply_default_provider_sort: bool = True,
                ) -> tuple[list[dict] | None, dict | None, httpx.Response | None]:
                    chat_payload = build_fast_openrouter_payload(
                        model_id=model_id,
                        prompt=body.prompt,
                        size=pixel_size,
                        modalities=mods,
                        aspect_ratio=resolved_aspect,
                        reference_image=reference_image,
                        allow_fallbacks=fallbacks,
                        image_size_tier=tier,
                        provider_sort=provider_sort,
                        apply_default_provider_sort=apply_default_provider_sort,
                    )
                    chat_resp = await post_openrouter_json(
                        f"{openrouter_base}/chat/completions",
                        headers=headers,
                        json_payload=chat_payload,
                    )
                    if chat_resp.status_code >= 400:
                        return None, None, chat_resp
                    chat_data = chat_resp.json()
                    collected = _collect_openrouter_images(chat_data) if isinstance(chat_data, dict) else None
                    if collected:
                        body.image_size_tier = tier or gemini_image_size_for_model(model_id, pixel_size)
                    return collected, chat_data if isinstance(chat_data, dict) else None, chat_resp

                async def _openrouter_chat_image_with_retries() -> tuple[list[dict] | None, dict | None, httpx.Response | None]:
                    # Gemini Pro: prefer stable 1K + provider fallbacks before latency-sorted hops.
                    gemini_pro = "gemini" in model_id.lower() and "pro" in model_id.lower()
                    if gemini_pro:
                        strategies: list[dict] = [
                            {
                                "pixel_size": safe_1k_size,
                                "mods": ["image", "text"],
                                "fallbacks": True,
                                "tier": "1K",
                                "provider_sort": None,
                                "apply_default_provider_sort": False,
                            },
                            {
                                "pixel_size": body.size,
                                "mods": modalities,
                                "fallbacks": True,
                                "tier": body.image_size_tier or "1K",
                                "provider_sort": None,
                                "apply_default_provider_sort": False,
                            },
                            {
                                "pixel_size": safe_1k_size,
                                "mods": ["image", "text"],
                                "fallbacks": True,
                                "tier": "1K",
                                "provider_sort": "throughput",
                                "apply_default_provider_sort": False,
                            },
                            {
                                "pixel_size": safe_1k_size,
                                "mods": ["image"],
                                "fallbacks": True,
                                "tier": "1K",
                                "provider_sort": None,
                                "apply_default_provider_sort": False,
                            },
                            {
                                "pixel_size": body.size,
                                "mods": modalities,
                                "fallbacks": allow_fallbacks,
                                "tier": body.image_size_tier,
                                "provider_sort": "latency",
                                "apply_default_provider_sort": False,
                            },
                        ]
                    else:
                        strategies = [
                            {
                                "pixel_size": body.size,
                                "mods": modalities,
                                "fallbacks": allow_fallbacks,
                                "tier": body.image_size_tier,
                                "provider_sort": "latency",
                                "apply_default_provider_sort": False,
                            },
                            {
                                "pixel_size": safe_1k_size,
                                "mods": ["image", "text"],
                                "fallbacks": True,
                                "tier": "1K",
                                "provider_sort": None,
                                "apply_default_provider_sort": False,
                            },
                            {
                                "pixel_size": safe_1k_size,
                                "mods": ["image"],
                                "fallbacks": False,
                                "tier": "1K",
                                "provider_sort": None,
                                "apply_default_provider_sort": False,
                            },
                            {
                                "pixel_size": body.size,
                                "mods": modalities,
                                "fallbacks": allow_fallbacks,
                                "tier": body.image_size_tier,
                                "provider_sort": None,
                                "apply_default_provider_sort": False,
                            },
                            {
                                "pixel_size": safe_1k_size,
                                "mods": ["image"],
                                "fallbacks": True,
                                "tier": "1K",
                                "provider_sort": "latency",
                                "apply_default_provider_sort": False,
                            },
                        ]
                    last_out: list[dict] | None = None
                    last_data: dict | None = None
                    last_resp: httpx.Response | None = None
                    last_transport_exc: BaseException | None = None
                    for attempt, strat in enumerate(strategies):
                        if attempt > 0:
                            delay_idx = min(attempt - 1, len(OPENROUTER_EMPTY_IMAGE_RETRY_DELAYS_SEC) - 1)
                            await asyncio.sleep(OPENROUTER_EMPTY_IMAGE_RETRY_DELAYS_SEC[delay_idx])
                        try:
                            out, data, resp = await _try_openrouter_chat_completion(**strat)
                        except Exception as exc:
                            if not is_retryable_openrouter_transport_error(exc):
                                raise
                            last_transport_exc = exc
                            continue
                        last_out, last_data, last_resp = out, data, resp
                        last_transport_exc = None
                        if resp is not None and resp.status_code >= 400:
                            if resp.status_code in {408, 429, 500, 502, 503, 504}:
                                continue
                            return None, data, resp
                        if out:
                            return out, data, resp
                        if not is_transient_empty_openrouter_image_response(data, collected=out):
                            return None, data, resp
                    if last_transport_exc is not None and last_out is None and last_resp is None:
                        raise last_transport_exc
                    return last_out, last_data, last_resp

                out, data, resp = await _openrouter_chat_image_with_retries()
                if resp is not None and resp.status_code >= 400:
                    body_preview = (resp.text or "").strip()
                    detail_msg = body_preview
                    try:
                        j = resp.json()
                        if isinstance(j, dict):
                            billing.usage_source = j
                        detail_msg = (
                            (j.get("error") or {}).get("message")
                            or j.get("message")
                            or body_preview
                        )
                    except Exception:
                        detail_msg = body_preview
                    if body_preview.startswith("<!DOCTYPE html"):
                        detail_msg = "Upstream returned HTML page instead of JSON API response. Check OpenRouter base URL."
                    status = 402 if resp.status_code == 402 else 500
                    raise HTTPException(
                        status_code=status,
                        detail=f"OpenRouter image request failed ({resp.status_code}): {detail_msg[:500] or 'Image generation failed'}",
                    )
                if isinstance(data, dict):
                    billing.usage_source = data
                if out:
                    return await _finalize_image_response(
                        db, user, body, out, aspect_ratio=resolved_aspect,
                        routing=routing_reason,
                    )

                msg = ((data or {}).get("choices") or [{}])[0].get("message") or {}
                content_preview = str(msg.get("content") or "")[:300]
                text_only = isinstance(msg.get("content"), str) and bool(str(msg.get("content") or "").strip())
                if chat_image_model:
                    if text_only:
                        if not reference_image:
                            out_gen, usage_data = await _try_openrouter_images_generations()
                            if usage_data:
                                billing.usage_source = usage_data
                            if out_gen:
                                return await _finalize_image_response(
                                    db, user, body, out_gen, aspect_ratio=resolved_aspect,
                                    routing=routing_reason,
                                )
                        if modalities != ["image"]:
                            retry_out, retry_data, _ = await _try_openrouter_chat_completion(
                                pixel_size=safe_1k_size,
                                mods=["image"],
                                fallbacks=False,
                                tier="1K",
                            )
                            if isinstance(retry_data, dict):
                                billing.usage_source = retry_data
                            if retry_out:
                                return await _finalize_image_response(
                                    db, user, body, retry_out, aspect_ratio=resolved_aspect,
                                    routing=routing_reason,
                                )
                        raise HTTPException(
                            status_code=422,
                            detail=(
                                "The model returned text instead of an image. "
                                "Try another image model (e.g. Gemini 2.5 Flash Image) or shorten the prompt."
                            ),
                        )
                    if not text_only:
                        images_meta = msg.get("images")
                        top_keys = ",".join(sorted(list((data or {}).keys()))[:10])
                        raise HTTPException(
                            status_code=502,
                            detail=(
                                "The image provider returned an empty response after automatic retries. "
                                "Please try again, use a shorter prompt, or pick another image model. "
                                f"(debug: keys={top_keys}, "
                                f"images_field={type(images_meta).__name__}:{len(images_meta or [])})"
                            ).strip(),
                        )

                # Legacy / non-chat image models only: short fallback attempts.
                out_gen, usage_data = await _try_openrouter_images_generations()
                if usage_data:
                    billing.usage_source = usage_data
                if out_gen:
                    return await _finalize_image_response(
                        db, user, body, out_gen, aspect_ratio=resolved_aspect,
                        routing=routing_reason,
                    )

                if text_only:
                    raise HTTPException(
                        status_code=422,
                        detail=(
                            "The model returned text instead of an image. "
                            "Select an image-capable model in chat, or turn off the Image Generation tool for text prompts."
                        ),
                    )
                top_keys = ",".join(sorted(list((data or {}).keys()))[:10])
                raise HTTPException(
                    status_code=502,
                    detail=(
                        "The image provider returned an empty response after automatic retries. "
                        "Please try again, use a shorter prompt, or pick another image model. "
                        f"(debug: keys={top_keys})"
                    ).strip(),
                )

            response = await litellm.aimage_generation(**kwargs)
            billing.usage_source = response
            out = _collect_litellm_image_items(response)
            if out:
                return await _finalize_image_response(
                    db, user, body, out, aspect_ratio=resolved_aspect,
                    routing=routing_reason,
                )
        model_attempts = auto_candidates if auto_candidates else [None]
        last_failover_exc: BaseException | None = None
        for attempt_idx, candidate in enumerate(model_attempts):
            if candidate is None:
                attempt_routing = routing_reason
                attempt_model_id = model_id
                attempt_api_key = api_key
                attempt_base_url = base_url
                attempt_provider_type = provider_type
                attempt_ai_model = ai_model
            else:
                attempt_model_id = candidate.external_id
                attempt_ai_model = candidate.model
                attempt_api_key = decrypt_secret(candidate.connection.api_key_encrypted)
                attempt_base_url = candidate.connection.base_url
                attempt_provider_type = candidate.connection.provider_type
                attempt_routing = {
                    **(candidate.reason or {}),
                    "selected_model": candidate.external_id,
                    "score": candidate.score,
                    "requested_model": requested_model,
                    "candidate_models": [c.external_id for c in auto_candidates],
                    "attempt_index": attempt_idx,
                    "failover": attempt_idx > 0,
                }
                if attempt_idx > 0 and last_failover_exc is not None:
                    prev = (
                        last_failover_exc.detail
                        if isinstance(last_failover_exc, HTTPException)
                        else str(last_failover_exc)
                    )
                    attempt_routing["failover_from_error"] = str(prev)[:240]
            try:
                return await _attempt_one_model(
                    attempt_model_id=attempt_model_id,
                    attempt_api_key=attempt_api_key,
                    attempt_base_url=attempt_base_url,
                    attempt_provider_type=attempt_provider_type,
                    attempt_ai_model=attempt_ai_model,
                    attempt_routing=attempt_routing,
                )
            except HTTPException as attempt_exc:
                can_failover = (
                    bool(auto_candidates)
                    and attempt_idx + 1 < len(model_attempts)
                    and is_image_model_failover_error(attempt_exc)
                )
                if can_failover:
                    last_failover_exc = attempt_exc
                    continue
                raise
            except httpx.HTTPError as attempt_exc:
                detail = str(attempt_exc).strip() or attempt_exc.__class__.__name__
                if "disconnected" in detail.lower():
                    detail = (
                        "Image provider closed the connection before responding. "
                        "Please retry; if it persists, try another image model or check the OpenRouter connection."
                    )
                wrapped = HTTPException(status_code=502, detail=detail[:500])
                can_failover = (
                    bool(auto_candidates)
                    and attempt_idx + 1 < len(model_attempts)
                    and is_image_model_failover_error(wrapped)
                )
                if can_failover:
                    last_failover_exc = wrapped
                    continue
                success = False
                error_message = detail[:500]
                raise wrapped from attempt_exc
        if last_failover_exc is not None:
            if isinstance(last_failover_exc, HTTPException):
                raise last_failover_exc
            raise HTTPException(
                status_code=502,
                detail=str(last_failover_exc)[:500],
            ) from last_failover_exc
    except HTTPException as exc:
        success = False
        detail = exc.detail
        error_message = detail if isinstance(detail, str) else str(detail)
        raise
    except httpx.HTTPError as exc:
        success = False
        msg = str(exc).strip() or exc.__class__.__name__
        if "disconnected" in msg.lower():
            msg = (
                "Image provider closed the connection before responding. "
                "Please retry; if it persists, try another image model or check the OpenRouter connection."
            )
        error_message = msg[:500]
        raise HTTPException(status_code=502, detail=msg) from exc
    except Exception as exc:
        success = False
        # Log the full exception server-side; return a generic message to the
        # client so internal details (tracebacks, connection strings, library
        # internals) are not leaked through the API response.
        import logging

        logging.getLogger("app.api.images").exception("Unhandled error during image generation")
        error_message = "Image generation failed due to an internal error"
        raise HTTPException(status_code=500, detail=error_message) from exc
    finally:
        elapsed_ms = (time.perf_counter() - generation_start) * 1000
        commit_error: Exception | None = None
        try:
            await _close_image_request_transaction(db, success=success)
        except Exception as exc:
            import logging

            logging.getLogger("app.api.images").exception(
                "Failed to close image request transaction before billing"
            )
            try:
                await db.rollback()
            except Exception:
                pass
            if success:
                success = False
                error_message = "Image persistence failed"
                commit_error = exc

        settled = False
        try:
            async with AsyncSessionLocal() as log_db:
                await log_image_usage(
                    log_db,
                    user=user,
                    capture=billing,
                    prompt=body.prompt,
                    response_time_ms=elapsed_ms,
                    success=success,
                    error_message=error_message,
                    source_ip=request.client.host if request.client else None,
                    operation=body.operation,
                    budget_reservation_id=budget_reservation_id,
                )
                await log_db.commit()
                settled = True
        except Exception:
            import logging

            logging.getLogger("app.api.images").exception(
                "Image usage settlement failed; releasing reservation when possible"
            )
        if budget_reservation_id and not settled:
            try:
                async with AsyncSessionLocal() as release_db:
                    await release(release_db, budget_reservation_id)
                    await release_db.commit()
            except Exception:
                import logging

                logging.getLogger("app.api.images").exception(
                    "Failed to release image budget reservation after billing error"
                )
        if commit_error is not None:
            raise HTTPException(
                status_code=500,
                detail="Image persistence failed due to an internal error",
            ) from commit_error
