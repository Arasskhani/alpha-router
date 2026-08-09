"""OpenRouter implementation of the provider-neutral video contract."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from app.services.openrouter_video_service import (
    build_video_generation_payload,
    download_video_bytes,
    extract_job_ids,
    extract_video_download_url,
    frame_image_from_data_url,
    job_status,
    poll_video_job,
    submit_video_job,
)
from app.services.video_providers.contracts import (
    NormalizedVideoRequest,
    ProviderAssetRef,
    ProviderJobRef,
    ProviderJobSnapshot,
    VideoProviderAdapter,
    VideoUsage,
)


def _status(value: str) -> str:
    if value == "completed":
        return "completed"
    if value == "cancelled":
        return "cancelled"
    if value == "failed":
        return "failed"
    if value in {"queued", "submitted"}:
        return "submitted"
    return "running"


class OpenRouterVideoAdapter:
    provider_type = "openrouter"
    adapter_version = "openrouter-v1"

    async def submit(
        self,
        *,
        api_key: str,
        base_url: str | None,
        request: NormalizedVideoRequest,
    ) -> ProviderJobRef:
        frame_images = None
        if request.reference_image is not None:
            import base64

            mime = request.reference_image_mime or "image/png"
            data_url = f"data:{mime};base64,{base64.b64encode(request.reference_image).decode('ascii')}"
            frame_images = [frame_image_from_data_url(data_url)]
        payload = build_video_generation_payload(
            model_id=request.model_id,
            prompt=request.prompt,
            duration=request.duration_seconds,
            resolution=request.resolution,
            aspect_ratio=request.aspect_ratio,
            generate_audio=request.generate_audio,
            frame_images=frame_images,
            seed=request.seed,
        )
        response = await submit_video_job(
            api_key=api_key,
            base_url=base_url,
            payload=payload,
        )
        provider_job_id, polling_url = extract_job_ids(response)
        if not provider_job_id:
            raise ValueError("OpenRouter did not return a video job id")
        return ProviderJobRef(
            provider_type=self.provider_type,
            provider_job_id=provider_job_id,
            polling_url=polling_url,
            cancel_supported=False,
        )

    async def poll(
        self,
        *,
        api_key: str,
        base_url: str | None,
        job: ProviderJobRef,
    ) -> ProviderJobSnapshot:
        response = await poll_video_job(
            api_key=api_key,
            base_url=base_url,
            provider_job_id=job.provider_job_id,
            polling_url=job.polling_url,
        )
        state = _status(job_status(response))
        asset_url = extract_video_download_url(response, base_url=base_url) if state == "completed" else None
        return ProviderJobSnapshot(
            state=state,
            provider_status=str(response.get("status") or "") or None,
            provider_job_id=job.provider_job_id,
            asset_url=asset_url,
            error_message=str(response.get("error") or response.get("message") or "")[:2000] or None,
            raw=response,
        )

    async def cancel(
        self,
        *,
        api_key: str,
        base_url: str | None,
        job: ProviderJobRef,
    ) -> bool:
        # OpenRouter currently has no documented cancel operation for /videos.
        return False

    async def fetch_result(
        self,
        *,
        api_key: str,
        base_url: str | None,
        snapshot: ProviderJobSnapshot,
    ) -> ProviderAssetRef:
        if not snapshot.asset_url:
            raise ValueError("Provider completed without a video asset URL")
        host = (urlparse(snapshot.asset_url).hostname or "").lower()
        is_api_asset = host == "openrouter.ai" or host.endswith(".openrouter.ai")
        return ProviderAssetRef(
            url=snapshot.asset_url,
            mime_type=snapshot.asset_mime or "video/mp4",
            requires_auth=is_api_asset,
            allowed_hosts=("openrouter.ai",) if is_api_asset else (),
        )

    def normalize_usage(self, snapshot: ProviderJobSnapshot) -> VideoUsage:
        payload: dict[str, Any] = snapshot.raw
        usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
        quantity = usage.get("duration_seconds") or usage.get("duration") or payload.get("duration")
        cost = usage.get("cost") or payload.get("cost") or payload.get("total_cost")
        try:
            quantity_value = float(quantity) if quantity is not None else None
        except (TypeError, ValueError):
            quantity_value = None
        try:
            cost_value = float(cost) if cost is not None else None
        except (TypeError, ValueError):
            cost_value = None
        return VideoUsage(quantity=quantity_value, unit="second" if quantity_value else "clip", cost_usd=cost_value, raw=payload)

