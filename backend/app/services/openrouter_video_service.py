"""OpenRouter async video generation client (submit / poll / download)."""

from __future__ import annotations

import contextlib
import re
from typing import Any
from urllib.parse import urlparse

import httpx

from app.config import get_settings
from app.core.constants import OPENROUTER_HOST, normalize_openrouter_base_url
from app.services.openrouter_image_service import build_openrouter_headers
from app.services.provider_http import get_provider_rest_client, provider_connect_timeout

ALLOWED_VIDEO_RESOLUTIONS = frozenset({"480p", "720p", "1080p", "1K", "2K", "4K"})
ALLOWED_VIDEO_ASPECT_RATIOS = frozenset({"16:9", "9:16", "1:1", "3:2", "2:3", "4:3", "3:4", "21:9"})
ALLOWED_VIDEO_MIME_TYPES = frozenset({"video/mp4", "video/webm"})
_OPENROUTER_HOST_SUFFIX = OPENROUTER_HOST


def normalize_video_resolution(value: str | None) -> str:
    raw = (value or "720p").strip()
    if raw.lower() == "1k":
        return "1K"
    if raw.lower() == "2k":
        return "2K"
    if raw.lower() == "4k":
        return "4K"
    low = raw.lower()
    for allowed in ALLOWED_VIDEO_RESOLUTIONS:
        if allowed.lower() == low:
            return allowed
    return "720p"


def normalize_video_aspect_ratio(value: str | None) -> str | None:
    raw = (value or "").strip()
    if not raw:
        return None
    if raw in ALLOWED_VIDEO_ASPECT_RATIOS:
        return raw
    return None


def parse_video_duration(seconds: object | None) -> int | None:
    """Parse a requested clip length. Never clamps to a platform default."""
    if seconds is None or isinstance(seconds, bool):
        return None
    try:
        value = int(seconds)
    except (TypeError, ValueError):
        return None
    if value < 1:
        return None
    return value


def catalog_video_durations(raw: object | None) -> list[int]:
    if not isinstance(raw, list):
        return []
    out: list[int] = []
    seen: set[int] = set()
    for item in raw:
        parsed = parse_video_duration(item)
        if parsed is None or parsed in seen:
            continue
        seen.add(parsed)
        out.append(parsed)
    return out


def openrouter_videos_base(base_url: str | None) -> str:
    return f"{normalize_openrouter_base_url(base_url)}/videos"


def build_video_generation_payload(
    *,
    model_id: str,
    prompt: str,
    duration: int | None = None,
    resolution: str | None = "720p",
    aspect_ratio: str | None = "16:9",
    generate_audio: bool = False,
    frame_images: list[dict[str, Any]] | None = None,
    seed: int | None = None,
) -> dict[str, Any]:
    """Build OpenRouter POST /videos body. Never includes callback_url (no inbound webhook)."""
    parsed_duration = parse_video_duration(duration)
    if parsed_duration is None:
        raise ValueError("duration is required")
    payload: dict[str, Any] = {
        "model": (model_id or "").strip(),
        "prompt": (prompt or "").strip(),
        "duration": parsed_duration,
        "resolution": normalize_video_resolution(resolution),
        "generate_audio": bool(generate_audio),
    }
    aspect = normalize_video_aspect_ratio(aspect_ratio)
    if aspect:
        payload["aspect_ratio"] = aspect
    if frame_images:
        payload["frame_images"] = frame_images
    if seed is not None:
        with contextlib.suppress(TypeError, ValueError):
            payload["seed"] = int(seed)
    return payload


def frame_image_from_data_url(data_url: str, *, frame_type: str = "first_frame") -> dict[str, Any]:
    return {
        "type": "image_url",
        "image_url": {"url": data_url},
        "frame_type": frame_type if frame_type in ("first_frame", "last_frame") else "first_frame",
    }


def _is_allowed_openrouter_url(url: str, *, base_url: str | None) -> bool:
    try:
        parsed = urlparse(url)
    except Exception:  # noqa: BLE001 -- external/optional dependency; falls back (return False)
        return False
    if parsed.scheme not in ("https", "http"):
        return False
    host = (parsed.hostname or "").lower()
    if host.endswith(_OPENROUTER_HOST_SUFFIX):
        return True
    if base_url:
        try:
            base_host = (urlparse(base_url).hostname or "").lower()
        except Exception:  # noqa: BLE001 -- falls back to a safe default value
            base_host = ""
        if base_host and host == base_host:
            return True
    return False


async def submit_video_job(
    *,
    api_key: str,
    base_url: str | None,
    payload: dict[str, Any],
    referer: str | None = None,
) -> dict[str, Any]:
    url = openrouter_videos_base(base_url)
    headers = build_openrouter_headers(api_key, referer=referer)
    client = get_provider_rest_client()
    timeout = httpx.Timeout(get_settings().provider_http_timeout_seconds, connect=provider_connect_timeout())
    response = await client.post(url, headers=headers, json=payload, timeout=timeout)
    if response.status_code >= 400:
        detail = (response.text or "")[:2000]
        raise httpx.HTTPStatusError(
            f"OpenRouter video submit failed: {response.status_code} {detail}",
            request=response.request,
            response=response,
        )
    data = response.json()
    if not isinstance(data, dict):
        raise ValueError("OpenRouter video submit returned a non-object payload")
    return data


async def poll_video_job(
    *,
    api_key: str,
    base_url: str | None,
    provider_job_id: str | None = None,
    polling_url: str | None = None,
    referer: str | None = None,
) -> dict[str, Any]:
    headers = build_openrouter_headers(api_key, referer=referer)
    client = get_provider_rest_client()
    timeout = httpx.Timeout(30.0, connect=provider_connect_timeout())

    url = (polling_url or "").strip()
    if url:
        if not _is_allowed_openrouter_url(url, base_url=base_url):
            raise ValueError("Refusing to poll non-OpenRouter video URL")
    else:
        job_id = (provider_job_id or "").strip()
        if not job_id:
            raise ValueError("provider_job_id or polling_url is required")
        if not re.fullmatch(r"[A-Za-z0-9._:-]{1,255}", job_id):
            raise ValueError("Invalid provider_job_id")
        url = f"{openrouter_videos_base(base_url)}/{job_id}"

    response = await client.get(url, headers=headers, timeout=timeout)
    if response.status_code >= 400:
        detail = (response.text or "")[:2000]
        raise httpx.HTTPStatusError(
            f"OpenRouter video poll failed: {response.status_code} {detail}",
            request=response.request,
            response=response,
        )
    data = response.json()
    if not isinstance(data, dict):
        raise ValueError("OpenRouter video poll returned a non-object payload")
    return data


def extract_job_ids(payload: dict[str, Any]) -> tuple[str | None, str | None]:
    job_id = payload.get("id") or payload.get("job_id")
    polling_url = payload.get("polling_url") or payload.get("poll_url")
    return (
        str(job_id).strip() if job_id else None,
        str(polling_url).strip() if polling_url else None,
    )


def job_status(payload: dict[str, Any]) -> str:
    status = str(payload.get("status") or "").strip().lower()
    if status in {"completed", "complete", "succeeded", "success"}:
        return "completed"
    if status in {"failed", "error", "cancelled", "canceled"}:
        return "failed" if status != "cancelled" and status != "canceled" else "cancelled"
    if status in {"queued", "pending", "submitted"}:
        return "queued"
    if status in {"running", "processing", "in_progress", "in-progress"}:
        return "running"
    return status or "running"


def extract_video_download_url(payload: dict[str, Any], *, base_url: str | None = None) -> str | None:
    """Pick a downloadable video URL from a completed OpenRouter job payload."""
    candidates: list[str] = []
    for key in ("url", "download_url", "content_url"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            candidates.append(value.strip())

    unsigned = payload.get("unsigned_urls")
    if isinstance(unsigned, list):
        for item in unsigned:
            if isinstance(item, str) and item.strip():
                candidates.append(item.strip())
            elif isinstance(item, dict):
                u = item.get("url")
                if isinstance(u, str) and u.strip():
                    candidates.append(u.strip())

    assets = payload.get("assets") or payload.get("data") or payload.get("videos")
    if isinstance(assets, list):
        for item in assets:
            if isinstance(item, str) and item.strip():
                candidates.append(item.strip())
            elif isinstance(item, dict):
                for key in ("url", "download_url", "content_url"):
                    u = item.get(key)
                    if isinstance(u, str) and u.strip():
                        candidates.append(u.strip())

    job_id = payload.get("id")
    if job_id and not candidates:
        # Content endpoint fallback documented by OpenRouter cookbook.
        candidates.append(f"{openrouter_videos_base(base_url)}/{job_id}/content")

    for url in candidates:
        if url.startswith("data:"):
            return url
        if _is_allowed_openrouter_url(url, base_url=base_url):
            return url
        # Some providers return CDN URLs; allow https only and rely on SSRF guard at fetch time.
        try:
            parsed = urlparse(url)
        except Exception:  # noqa: BLE001 -- one bad item must not abort the batch
            continue
        if parsed.scheme == "https" and parsed.hostname:
            return url
    return None
