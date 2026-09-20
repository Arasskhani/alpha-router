"""Image generation (independent of Open WebUI) — OpenAI-compatible images API."""

from __future__ import annotations

import asyncio
import base64
import contextlib
import datetime
import re
import time
import uuid
from urllib.parse import urlparse

import httpx
import litellm
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_active_user
from app.database import AsyncSessionLocal, get_db
from app.models.connection import Connection
from app.models.model_catalog import AIModel
from app.models.user import User
from app.services.client_ip import resolve_client_ip
from app.services.secret_crypto import decrypt_secret
from app.services.image_model_resolver import (
    is_image_model_failover_error,
    list_auto_router_image_candidates,
)
from app.services.model_access_service import resolve_access_subject, user_can_access_model
from app.services.budget_reservation_service import (
    reservation_hold_usd,
    reservation_key,
    reserve,
)
from app.config import get_settings
from app.services.rate_limit import check_generation_rate_limit, generation_subject
from app.services.media_authorization_service import MediaAccessAction, load_authorized_media_asset
from app.services.openrouter_image_service import (
    OPENROUTER_EMPTY_IMAGE_RETRY_DELAYS_SEC,
    OPENROUTER_IMAGE_ENDPOINT_PATHS,
    OPENROUTER_IMAGE_MAX_ATTEMPTS,
    build_fast_openrouter_payload,
    build_openrouter_headers,
    build_openrouter_image_endpoint_payload,
    gemini_image_size_for_model,
    image_request_timeout,
    is_openai_gpt_image_model,
    is_openrouter_auto_model,
    is_retryable_openrouter_transport_error,
    is_transient_empty_openrouter_image_response,
    openrouter_image_modalities,
    openrouter_input_references,
    openrouter_message_is_text_only,
    optimize_openrouter_image_model,
    post_openrouter_json,
    prefer_openrouter_images_generations,
)
from app.services.storage_service import (
    media_input_limit,
    media_content_hash,
    read_media_bytes,
    resolve_media_blob,
)
from app.services.user_chat_storage_service import finalize_chat_session_image
from app.services.failure_details import CODE_CANCELLED, describe_failure, failure_message
from app.services.image_billing_service import ImageBillingCapture, log_image_usage
from app.services.image_attempt_service import image_attempt_outcome, record_image_attempt
from app.services.chat_channel_guard import assert_session_allows_model_generation
from app.services.chat_tool_access_service import assert_tool_for_user
from app.services.project_billing_service import resolve_project_id_for_request
from app.services.project_media_service import persist_scoped_chat_media
from app.services.llm_providers import (
    external_id_lookup_candidates,
    litellm_model_for_provider,
    normalize_model_id,
    resolve_litellm_provider,
)
from app.services.openrouter_image_service import prepare_image_generation_prompt
from app.core.constants import normalize_openrouter_base_url

router = APIRouter(prefix="/api/images", tags=["images"])
_ALPHA_ROUTER_MEDIA_PATH = re.compile(r"/api/chat/media/(\d+)/file/?(?:\?.*)?$")
_PROJECT_MEDIA_PATH = re.compile(r"/api/projects/([^/]+)/media/(\d+)/download/?(?:\?.*)?$")
_AUTO_ROUTER_TOTAL_TIMEOUT_SECONDS = 45.0
_AUTO_ROUTER_MODEL_TIMEOUT_SECONDS = 20.0


class ImageClientDisconnected(Exception):
    """Internal signal used to stop upstream work after the browser disconnects."""


async def _await_image_work(
    work,
    *,
    request: Request,
    timeout_seconds: float,
):
    """Await upstream work with a hard deadline and client-disconnect cancellation."""
    task = asyncio.create_task(work)
    deadline = time.monotonic() + max(0.1, float(timeout_seconds))
    try:
        while not task.done():
            if await request.is_disconnected():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
                raise ImageClientDisconnected()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
                raise TimeoutError()
            await asyncio.wait({task}, timeout=min(0.5, remaining))
        return await task
    except BaseException:
        if not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        raise


def parse_alpha_router_media_asset_id(reference: str) -> int | None:
    """Extract a media asset id from Alpharouter /api/chat/media/{id}/file URLs."""
    ref = (reference or "").strip()
    if not ref:
        return None
    path = urlparse(ref).path if ref.startswith(("http://", "https://")) else ref.split("?")[0]
    match = _ALPHA_ROUTER_MEDIA_PATH.search(path)
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def parse_project_media_ref(reference: str) -> tuple[str, int] | None:
    """Extract project id and media id from project download URLs."""
    ref = (reference or "").strip()
    if not ref:
        return None
    path = urlparse(ref).path if ref.startswith(("http://", "https://")) else ref.split("?")[0]
    match = _PROJECT_MEDIA_PATH.search(path)
    if not match:
        return None
    try:
        return match.group(1), int(match.group(2))
    except (TypeError, ValueError):
        return None


async def resolve_reference_image_for_upstream(
    db: AsyncSession,
    user: User,
    reference_image: str | None,
) -> str | None:
    """Turn Alpharouter media paths into data URLs external providers can consume."""
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

    project_ref = parse_project_media_ref(ref)
    if project_ref is not None:
        from app.services.project_media_service import read_project_media_bytes

        project_id, media_id = project_ref
        loaded = await read_project_media_bytes(db, project_id=project_id, media_id=media_id, user=user)
        if loaded is None:
            raise HTTPException(status_code=404, detail="Reference image not found")
        row, data = loaded
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


_normalize_model_id = normalize_model_id


_normalize_openrouter_base = normalize_openrouter_base_url


#: Most images one request may ask for. The budget hold has always quoted
#: ``min(4, n)``, so this is the number the user was told they would be charged
#: for. ``n`` itself was unbounded and passed to the provider verbatim, and the
#: bill counted what came back - so a request for 50 was admitted against a hold
#: for 4, charged in full, and only the *next* request was refused. Making the
#: schema say 4 means the quote and the request are the same number.
IMAGE_MAX_BATCH = 4


class ImageRequest(BaseModel):
    model: str
    prompt: str
    n: int = Field(1, ge=1, le=IMAGE_MAX_BATCH)
    size: str = "1024x1024"
    aspect_ratio: str | None = None
    operation: str = "generation"  # generation | img2img | imagine | outpaint
    reference_image: str | None = None  # data URL or http(s) URL for image-to-image
    chat_session_id: str | None = None
    project_id: str | None = None
    persist: bool = True
    image_size_tier: str | None = None
    routing: dict[str, object] | None = None
    assistant_client_message_id: str | None = None


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


def _openrouter_modalities(model_id: str, ai_model: AIModel | None = None) -> list[str]:
    return openrouter_image_modalities(
        model_id,
        pricing_raw=getattr(ai_model, "pricing_raw", None),
    )


def _is_output_modality_404(resp: httpx.Response | None) -> bool:
    """True for OpenRouter's "no endpoints ... requested output modalities" 404."""
    if resp is None or resp.status_code != 404:
        return False
    try:
        body = (resp.text or "").lower()
    except Exception:  # noqa: BLE001 -- external/optional dependency; falls back (return False)
        return False
    return "output modalit" in body and "no endpoint" in body


def _prefer_openrouter_images_generations(model_id: str, ai_model: AIModel | None = None) -> bool:
    return prefer_openrouter_images_generations(
        model_id,
        pricing_raw=getattr(ai_model, "pricing_raw", None),
    )


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
        except Exception:  # noqa: BLE001 -- external/optional dependency; falls back (return None)
            return None
    if not data:
        return None
    try:
        from app.services.image_decode_policy import image_dimensions

        return await asyncio.to_thread(image_dimensions, data)
    except Exception:  # noqa: BLE001 -- external/optional dependency; falls back (return None)
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
    except Exception:  # noqa: BLE001 -- external/optional dependency; falls back (return None)
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
    project_id: str | None = None,
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

        url = await persist_scoped_chat_media(
            db,
            user=user,
            project_id=project_id,
            kind="image",
            blob=blob,
            mime=mime,
            file_name="generated.png",
            source_model=model,
            source_prompt=prompt,
            chat_session_id=chat_session_id,
        )
        out.append({"url": url})
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
        project_id = await resolve_project_id_for_request(
            db,
            user=user,
            chat_session_id=body.chat_session_id,
            project_id=body.project_id,
        )
        items = await _persist_image_data_items(
            db,
            user=user,
            items=items,
            model=body.model,
            prompt=body.prompt,
            chat_session_id=body.chat_session_id,
            max_items=max(1, min(IMAGE_MAX_BATCH, int(body.n or 1))),
            project_id=project_id,
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
        url_val = image_url_field.get("url") or image_url_field.get("uri") or image_url_field.get("data")
    url_val = url_val or obj.get("url") or obj.get("uri")
    inline = obj.get("inline_data") or obj.get("inlineData")
    b64_val = obj.get("b64_json") or obj.get("b64Json") or obj.get("image_base64") or obj.get("imageBase64")
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


def _collect_openrouter_images(data: dict) -> list[dict]:  # noqa: C901 -- Phase 4 split; complexity must not grow
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
                    part_url = part_url or (str(part.get("data")) if part.get("data") else None)
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
    db: AsyncSession,
    raw_model: str,
    *,
    access_user_id: int | None = None,
) -> tuple[str, str | None, str | None, str | None, AIModel | None]:
    model_id = _normalize_model_id(raw_model)
    subject = await resolve_access_subject(db, user_id=access_user_id) if access_user_id is not None else None
    row: AIModel | None = None
    if model_id.startswith("model::"):
        try:
            model_pk = int(model_id.split("::", 1)[1])
        except Exception:  # noqa: BLE001 -- falls back to a safe default value
            model_pk = None
        if model_pk is not None:
            row = (
                (
                    await db.execute(
                        select(AIModel).where(AIModel.id == model_pk, AIModel.is_enabled == True)  # noqa: E712
                    )
                )
                .scalars()
                .first()
            )
        if row:
            conn = await db.get(Connection, row.connection_id)
            if conn and conn.is_active and (subject is None or await user_can_access_model(db, row, subject)):
                return (
                    row.external_id,
                    decrypt_secret(conn.api_key_encrypted),
                    conn.base_url,
                    conn.provider_type,
                    row,
                )
            row = None

    if not row:
        # external_id can exist in multiple connections; prefer latest model bound to an active connection.
        id_candidates = external_id_lookup_candidates(model_id)
        candidates = (
            (
                await db.execute(
                    select(AIModel, Connection)
                    .join(Connection, Connection.id == AIModel.connection_id)
                    .where(
                        AIModel.external_id.in_(id_candidates),
                        AIModel.is_enabled == True,  # noqa: E712
                        Connection.is_active == True,  # noqa: E712
                    )
                    .order_by(AIModel.id.desc())
                )
            ).all()
            if id_candidates
            else []
        )
        for cand_row, conn in candidates:
            if subject is None or await user_can_access_model(db, cand_row, subject):
                return (
                    cand_row.external_id,
                    decrypt_secret(conn.api_key_encrypted),
                    conn.base_url,
                    conn.provider_type,
                    cand_row,
                )

    if not row:
        return model_id, None, None, None, None
    return model_id, None, None, None, None


def _classify(exc: BaseException) -> tuple[str, int | None]:
    """Failure code and upstream status for an image request, never blank.

    `str(exc)` is empty for every httpx timeout and a bare ConnectError, so an
    image failure used to reach API Logs with a code of None and, on the
    per-attempt events, an empty message - the same hole that made video
    failures read "Video generation failed" and nothing else.
    """
    detail = describe_failure(exc)
    return detail.code, detail.http_status


@router.post("/generate")
async def generate_image(  # noqa: C901 -- Phase 4 split; complexity must not grow
    request: Request,
    body: ImageRequest,
    user: User = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
):
    await assert_tool_for_user(db, "image_generation", user_id=user.id)
    await assert_session_allows_model_generation(db, body.chat_session_id)
    await check_generation_rate_limit(
        "image",
        generation_subject(user_id=user.id, api_key_id=None),
        get_settings().image_generation_rate_limit_per_min,
    )
    generation_start = time.perf_counter()
    billing = ImageBillingCapture(model_id=_normalize_model_id(body.model))
    budget_reservation_id: str | None = None
    routing_reason: dict[str, object] | None = body.routing
    success = True
    error_message: str | None = None
    # Classified alongside the message so API Logs can filter image failures the
    # same way it filters chat and video ones; without a code the Error Code
    # filter simply never matches an image row.
    error_code: str | None = None
    http_status: int | None = None
    image_request_id = str(uuid.uuid4())
    current_attempt_started_at: datetime.datetime | None = None
    current_attempt_source_count = 0
    response_out: dict | None = None

    project_id_for_billing = await resolve_project_id_for_request(
        db,
        user=user,
        chat_session_id=body.chat_session_id,
        project_id=body.project_id,
    )

    async def _record(**kwargs):
        await record_image_attempt(project_id=project_id_for_billing, **kwargs)

    async def _ok_response(
        items: list[dict],
        *,
        aspect_ratio: str | None = None,
        routing: dict[str, object] | None = None,
    ) -> dict:
        nonlocal response_out
        response_out = await _finalize_image_response(
            db,
            user,
            body,
            items,
            aspect_ratio=aspect_ratio,
            routing=routing,
        )
        return response_out

    requested_model = _normalize_model_id(body.model)
    auto_router_requested = is_openrouter_auto_model(requested_model)
    using_auto_router = False
    resolve_task = asyncio.create_task(_resolve_image_model(db, body.model, access_user_id=user.id))

    try:
        model_id, api_key, base_url, provider_type, ai_model = await resolve_task
        billing.model_id = model_id
        billing.ai_model = ai_model
        billing.provider_type = provider_type

        auto_candidates = []
        if is_openrouter_auto_model(model_id) or auto_router_requested:
            using_auto_router = True
            auto_candidates = await list_auto_router_image_candidates(
                db,
                connection_id=ai_model.connection_id if ai_model else None,
                limit=2,
                access_user_id=user.id,
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
        requested_quantity = max(1, min(IMAGE_MAX_BATCH, int(body.n or 1)))
        hold = await reserve(
            db,
            user_id=user.id,
            alpha_router_api_key_id=None,
            amount_usd=await reservation_hold_usd(
                db,
                service_type="image",
                ai_model=ai_model,
                provider_type=provider_type or "unknown",
                model_id=model_id,
                quantity=float(requested_quantity),
                unit="image",
            ),
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
        upstream_prompt = prepare_image_generation_prompt(body.prompt)

        async def _attempt_one_model(  # noqa: C901 -- Phase 4 split; complexity must not grow
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
                "prompt": upstream_prompt,
                # The same number the hold quoted, not the raw field.
                "n": max(1, min(IMAGE_MAX_BATCH, int(body.n or 1))),
                "size": body.size,
            }
            if api_key:
                kwargs["api_key"] = api_key
            if base_url:
                kwargs["base_url"] = base_url
            llm_provider = resolve_litellm_provider(provider_type)
            if llm_provider:
                kwargs["custom_llm_provider"] = llm_provider
            kwargs["timeout"] = image_request_timeout()

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
                    input_refs = openrouter_input_references(reference_image)
                    img_resp: httpx.Response | None = None
                    for index, path in enumerate(OPENROUTER_IMAGE_ENDPOINT_PATHS):
                        is_last = index == len(OPENROUTER_IMAGE_ENDPOINT_PATHS) - 1
                        img_payload = build_openrouter_image_endpoint_payload(
                            path=path,
                            model=optimize_openrouter_image_model(model_id),
                            prompt=upstream_prompt,
                            n=max(1, min(IMAGE_MAX_BATCH, int(body.n or 1))),
                            size=body.size,
                            input_references=input_refs,
                        )
                        if img_payload is None:
                            continue
                        img_resp = await post_openrouter_json(
                            f"{openrouter_base}{path}",
                            headers=headers,
                            json_payload=img_payload,
                            read_timeout=image_request_timeout(),
                            max_attempts=(1 if using_auto_router else OPENROUTER_IMAGE_MAX_ATTEMPTS),
                            on_attempt_error=lambda _attempt, started_at, exc: billing.add_usage(
                                None,
                                started_at=started_at,
                                success=False,
                                error_message=failure_message(exc),
                            ),
                        )
                        if img_resp.status_code in {404, 405} and not is_last:
                            # This deployment does not expose this path; try the
                            # next one before recording a failed attempt.
                            continue
                        break
                    if img_resp is None:
                        return None, None
                    if img_resp.status_code >= 400:
                        try:
                            error_payload = img_resp.json()
                        except Exception:  # noqa: BLE001 -- falls back to a safe default value
                            error_payload = None
                        billing.add_usage(
                            error_payload,
                            started_at=img_resp.extensions.get("alpha_router_started_at"),
                            success=False,
                            error_message=(img_resp.text or "")[:2000],
                        )
                        return None, None
                    img_data = img_resp.json()
                    items = _collect_standard_image_payload(img_data) or None
                    billing.add_usage(
                        img_data if isinstance(img_data, dict) else None,
                        started_at=img_resp.extensions.get("alpha_router_started_at"),
                        success=bool(items),
                        quantity=len(items or []) or None,
                        error_message=(None if items else "Provider returned no image"),
                    )
                    return items, img_data if isinstance(img_data, dict) else None

                if _prefer_openrouter_images_generations(model_id, ai_model):
                    # Image-only models reject chat/completions outright, and the
                    # Image API takes a reference image via input_references.
                    out_gen, usage_data = await _try_openrouter_images_generations()
                    if out_gen:
                        return await _ok_response(
                            out_gen,
                            aspect_ratio=resolved_aspect,
                            routing=routing_reason,
                        )

                modalities = _openrouter_modalities(model_id, ai_model)
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
                        prompt=upstream_prompt,
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
                        max_attempts=(1 if using_auto_router else OPENROUTER_IMAGE_MAX_ATTEMPTS),
                        on_attempt_error=lambda _attempt, started_at, exc: billing.add_usage(
                            None,
                            started_at=started_at,
                            success=False,
                            error_message=failure_message(exc),
                        ),
                    )
                    if chat_resp.status_code >= 400:
                        try:
                            error_payload = chat_resp.json()
                        except Exception:  # noqa: BLE001 -- falls back to a safe default value
                            error_payload = None
                        billing.add_usage(
                            error_payload,
                            started_at=chat_resp.extensions.get("alpha_router_started_at"),
                            success=False,
                            error_message=(chat_resp.text or "")[:2000],
                        )
                        return (
                            None,
                            error_payload if isinstance(error_payload, dict) else None,
                            chat_resp,
                        )
                    chat_data = chat_resp.json()
                    collected = _collect_openrouter_images(chat_data) if isinstance(chat_data, dict) else None
                    billing.add_usage(
                        chat_data if isinstance(chat_data, dict) else None,
                        started_at=chat_resp.extensions.get("alpha_router_started_at"),
                        success=bool(collected),
                        quantity=len(collected or []) or None,
                        error_message=(None if collected else "Provider returned no image"),
                    )
                    if collected:
                        body.image_size_tier = tier or gemini_image_size_for_model(model_id, pixel_size)
                    return collected, chat_data if isinstance(chat_data, dict) else None, chat_resp

                async def _openrouter_chat_image_with_retries() -> tuple[
                    list[dict] | None, dict | None, httpx.Response | None
                ]:
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
                                "provider_sort": None,
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
                    if using_auto_router:
                        # Fast Auto Router gets one uptime-aware request per model;
                        # its outer loop owns failover and the total deadline.
                        strategies = strategies[:1]
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
                        # Text-only: bail out of the strategy grind so Auto Router can
                        # failover (or the outer image-only /generations path can run).
                        if openrouter_message_is_text_only(data):
                            return None, data, resp
                        if not is_transient_empty_openrouter_image_response(data, collected=out):
                            return None, data, resp
                    if last_transport_exc is not None and last_out is None and last_resp is None:
                        raise last_transport_exc
                    return last_out, last_data, last_resp

                out, data, resp = await _openrouter_chat_image_with_retries()
                if modalities != ["image"] and _is_output_modality_404(resp):
                    # Safety net for a stale or missing catalog snapshot: the model
                    # cannot emit text at all, so ask for image output only.
                    modalities = ["image"]
                    retry_out, retry_data, retry_resp = await _try_openrouter_chat_completion(
                        pixel_size=safe_1k_size,
                        mods=modalities,
                        fallbacks=allow_fallbacks,
                        tier="1K",
                    )
                    if retry_out:
                        return await _ok_response(
                            retry_out,
                            aspect_ratio=resolved_aspect,
                            routing=routing_reason,
                        )
                    if retry_resp is not None and retry_resp.status_code < 400:
                        # Reached the model this time; keep its payload for the
                        # text-only / empty-response handling below.
                        out, data, resp = retry_out, retry_data, retry_resp
                if resp is not None and resp.status_code >= 400:
                    body_preview = (resp.text or "").strip()
                    detail_msg = body_preview
                    try:
                        j = resp.json()
                        detail_msg = (j.get("error") or {}).get("message") or j.get("message") or body_preview
                    except Exception:  # noqa: BLE001 -- falls back to a safe default value
                        detail_msg = body_preview
                    if body_preview.startswith("<!DOCTYPE html"):
                        detail_msg = (
                            "Upstream returned HTML page instead of JSON API response. Check OpenRouter base URL."
                        )
                    status = 402 if resp.status_code == 402 else 500
                    raise HTTPException(
                        status_code=status,
                        detail=f"OpenRouter image request failed ({resp.status_code}): {detail_msg[:500] or 'Image generation failed'}",
                    )
                if out:
                    return await _ok_response(
                        out,
                        aspect_ratio=resolved_aspect,
                        routing=routing_reason,
                    )

                msg = ((data or {}).get("choices") or [{}])[0].get("message") or {}
                text_only = isinstance(msg.get("content"), str) and bool(str(msg.get("content") or "").strip())
                if chat_image_model:
                    if text_only:
                        if using_auto_router:
                            raise HTTPException(
                                status_code=422,
                                detail="The model returned text instead of an image.",
                            )
                        if not reference_image:
                            out_gen, usage_data = await _try_openrouter_images_generations()
                            if out_gen:
                                return await _ok_response(
                                    out_gen,
                                    aspect_ratio=resolved_aspect,
                                    routing=routing_reason,
                                )
                        if modalities != ["image"]:
                            retry_out, retry_data, _ = await _try_openrouter_chat_completion(
                                pixel_size=safe_1k_size,
                                mods=["image"],
                                fallbacks=False,
                                tier="1K",
                            )
                            if retry_out:
                                return await _ok_response(
                                    retry_out,
                                    aspect_ratio=resolved_aspect,
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
                if out_gen:
                    return await _ok_response(
                        out_gen,
                        aspect_ratio=resolved_aspect,
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

            litellm_started_at = datetime.datetime.utcnow()
            response = await litellm.aimage_generation(**kwargs)
            out = _collect_litellm_image_items(response)
            billing.add_usage(
                response,
                started_at=litellm_started_at,
                success=bool(out),
                quantity=len(out or []) or None,
            )
            if out:
                return await _ok_response(
                    out,
                    aspect_ratio=resolved_aspect,
                    routing=routing_reason,
                )
            raise HTTPException(
                status_code=502,
                detail="The image provider returned no image.",
            )

        model_attempts = auto_candidates if auto_candidates else [None]
        last_failover_exc: BaseException | None = None
        auto_deadline = generation_start + _AUTO_ROUTER_TOTAL_TIMEOUT_SECONDS if using_auto_router else None
        current_attempt_source_count = len(billing.usage_sources)
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
            attempt_started_at = datetime.datetime.utcnow()
            current_attempt_started_at = attempt_started_at
            current_attempt_source_count = len(billing.usage_sources)
            attempt_started = time.perf_counter()
            try:
                timeout_seconds = image_request_timeout()
                if auto_deadline is not None:
                    remaining = auto_deadline - time.perf_counter()
                    if remaining <= 0:
                        raise TimeoutError()
                    timeout_seconds = min(_AUTO_ROUTER_MODEL_TIMEOUT_SECONDS, remaining)
                result = await _await_image_work(
                    _attempt_one_model(
                        attempt_model_id=attempt_model_id,
                        attempt_api_key=attempt_api_key,
                        attempt_base_url=attempt_base_url,
                        attempt_provider_type=attempt_provider_type,
                        attempt_ai_model=attempt_ai_model,
                        attempt_routing=attempt_routing,
                    ),
                    request=request,
                    timeout_seconds=timeout_seconds,
                )
                await _record(
                    request_id=image_request_id,
                    user_id=user.id,
                    requested_model=requested_model,
                    model_id=attempt_model_id,
                    operation=body.operation,
                    attempt_index=attempt_idx,
                    started_at=attempt_started_at,
                    response_time_ms=(time.perf_counter() - attempt_started) * 1000,
                    success=True,
                    outcome="success",
                )
                return result
            except ImageClientDisconnected as attempt_exc:
                if len(billing.usage_sources) == current_attempt_source_count:
                    billing.add_usage(
                        None,
                        started_at=attempt_started_at,
                        success=False,
                        error_message="Client disconnected",
                    )
                await _record(
                    request_id=image_request_id,
                    user_id=user.id,
                    requested_model=requested_model,
                    model_id=attempt_model_id,
                    operation=body.operation,
                    attempt_index=attempt_idx,
                    started_at=attempt_started_at,
                    response_time_ms=(time.perf_counter() - attempt_started) * 1000,
                    success=False,
                    outcome="cancelled",
                    error_message="Client disconnected",
                )
                raise HTTPException(
                    status_code=499,
                    detail="Image generation stopped because the client disconnected.",
                ) from attempt_exc
            except TimeoutError as attempt_exc:
                wrapped = HTTPException(
                    status_code=504,
                    detail="Image model attempt timed out.",
                )
                if len(billing.usage_sources) == current_attempt_source_count:
                    billing.add_usage(
                        None,
                        started_at=attempt_started_at,
                        success=False,
                        error_message=str(wrapped.detail),
                    )
                await _record(
                    request_id=image_request_id,
                    user_id=user.id,
                    requested_model=requested_model,
                    model_id=attempt_model_id,
                    operation=body.operation,
                    attempt_index=attempt_idx,
                    started_at=attempt_started_at,
                    response_time_ms=(time.perf_counter() - attempt_started) * 1000,
                    success=False,
                    outcome="timeout",
                    error_message=str(wrapped.detail),
                )
                can_failover = bool(auto_candidates) and attempt_idx + 1 < len(model_attempts)
                if can_failover:
                    last_failover_exc = wrapped
                    continue
                raise wrapped from attempt_exc
            except HTTPException as attempt_exc:
                if attempt_exc.status_code >= 500 and len(billing.usage_sources) == current_attempt_source_count:
                    billing.add_usage(
                        None,
                        started_at=attempt_started_at,
                        success=False,
                        error_message=str(attempt_exc.detail),
                    )
                await _record(
                    request_id=image_request_id,
                    user_id=user.id,
                    requested_model=requested_model,
                    model_id=attempt_model_id,
                    operation=body.operation,
                    attempt_index=attempt_idx,
                    started_at=attempt_started_at,
                    response_time_ms=(time.perf_counter() - attempt_started) * 1000,
                    success=False,
                    outcome=image_attempt_outcome(attempt_exc),
                    error_message=str(attempt_exc.detail),
                )
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
                if len(billing.usage_sources) == current_attempt_source_count:
                    billing.add_usage(
                        None,
                        started_at=attempt_started_at,
                        success=False,
                        error_message=detail,
                    )
                await _record(
                    request_id=image_request_id,
                    user_id=user.id,
                    requested_model=requested_model,
                    model_id=attempt_model_id,
                    operation=body.operation,
                    attempt_index=attempt_idx,
                    started_at=attempt_started_at,
                    response_time_ms=(time.perf_counter() - attempt_started) * 1000,
                    success=False,
                    outcome=image_attempt_outcome(wrapped),
                    error_message=detail,
                )
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
                error_code, http_status = _classify(wrapped)
                raise wrapped from attempt_exc
        if last_failover_exc is not None:
            if isinstance(last_failover_exc, HTTPException):
                raise last_failover_exc
            raise HTTPException(
                status_code=502,
                detail=str(last_failover_exc)[:500],
            ) from last_failover_exc
    except asyncio.CancelledError as exc:
        success = False
        error_code = CODE_CANCELLED
        error_message = str(exc) or "Image generation cancelled"
        if len(billing.usage_sources) == current_attempt_source_count:
            billing.add_usage(
                None,
                started_at=current_attempt_started_at,
                success=False,
                error_message=error_message,
            )
        raise
    except HTTPException as exc:
        success = False
        detail = exc.detail
        error_message = detail if isinstance(detail, str) else str(detail)
        error_code, http_status = _classify(exc)
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
        error_code, http_status = _classify(exc)
        raise HTTPException(status_code=502, detail=msg) from exc
    except Exception as exc:
        success = False
        # Log the full exception server-side; return a generic message to the
        # client so internal details (tracebacks, connection strings, library
        # internals) are not leaked through the API response.
        import logging

        logging.getLogger("app.api.images").exception("Unhandled error during image generation")
        error_message = "Image generation failed due to an internal error"
        error_code, http_status = _classify(exc)
        raise HTTPException(status_code=500, detail=error_message) from exc
    finally:
        elapsed_ms = (time.perf_counter() - generation_start) * 1000
        commit_error: Exception | None = None
        try:
            await asyncio.shield(_close_image_request_transaction(db, success=success))
        except Exception as exc:
            import logging

            logging.getLogger("app.api.images").exception("Failed to close image request transaction before billing")
            with contextlib.suppress(Exception):
                await db.rollback()
            if success:
                success = False
                error_message = "Image persistence failed"
                commit_error = exc

        async def _settle_image_usage() -> int | None:
            for attempt in range(3):
                try:
                    async with AsyncSessionLocal() as log_db:
                        log_id = await log_image_usage(
                            log_db,
                            user=user,
                            capture=billing,
                            prompt=body.prompt,
                            response_time_ms=elapsed_ms,
                            success=success,
                            error_message=error_message,
                            error_code=error_code,
                            http_status=http_status,
                            source_ip=resolve_client_ip(request),
                            operation=body.operation,
                            budget_reservation_id=budget_reservation_id,
                            quantity=body.n,
                            project_id=project_id_for_billing,
                        )
                        if log_id and success and body.chat_session_id:
                            from app.services.user_chat_storage_service import (
                                attach_request_log_id_to_chat_message,
                            )

                            await attach_request_log_id_to_chat_message(
                                log_db,
                                user.id,
                                body.chat_session_id,
                                int(log_id),
                                client_message_id=body.assistant_client_message_id,
                            )
                        await log_db.commit()
                    return log_id
                except Exception:
                    if attempt < 2:
                        await asyncio.sleep(0.1 * (attempt + 1))
                        continue
                    import logging

                    from app.services.observability import increment

                    increment("budget_hold_leak")
                    logging.getLogger("app.api.images").exception(
                        "Image usage settlement failed after retries; reservation remains held for recovery"
                    )
            return None

        settled_log_id = await asyncio.shield(_settle_image_usage())
        if response_out is not None and settled_log_id:
            response_out["request_log_id"] = int(settled_log_id)
        if commit_error is not None:
            raise HTTPException(
                status_code=500,
                detail="Image persistence failed due to an internal error",
            ) from commit_error
