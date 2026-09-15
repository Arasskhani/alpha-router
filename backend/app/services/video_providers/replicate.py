"""Replicate prediction adapter.

Replicate is intentionally kept behind the same contract as OpenRouter:
prediction submission and polling are provider-specific, while orchestration,
storage, ACL and billing remain shared.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from app.services.video_providers.contracts import (
    NormalizedVideoRequest,
    ProviderAssetRef,
    ProviderJobRef,
    ProviderJobSnapshot,
    VideoUsage,
)
from app.config import get_settings
from app.services.provider_http import get_provider_rest_client, provider_connect_timeout


class ReplicateVideoAdapter:
    provider_type = "replicate"
    adapter_version = "replicate-v1"

    def _base(self, base_url: str | None) -> str:
        return (base_url or "https://api.replicate.com/v1").rstrip("/") + "/"

    def _headers(self, api_key: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    async def submit(self, *, api_key: str, base_url: str | None, request: NormalizedVideoRequest) -> ProviderJobRef:
        # Replicate model versions are represented by the catalog model id.
        input_payload: dict[str, Any] = {
            "prompt": request.prompt,
            "duration": request.duration_seconds,
            "resolution": request.resolution,
            "aspect_ratio": request.aspect_ratio,
            "generate_audio": request.generate_audio,
        }
        if request.reference_image is not None:
            import base64

            input_payload["image"] = (
                f"data:{request.reference_image_mime or 'image/png'};base64,"
                f"{base64.b64encode(request.reference_image).decode('ascii')}"
            )
        response = await self._request(
            "POST",
            urljoin(self._base(base_url), "predictions"),
            api_key,
            json_body={"version": request.model_id, "input": input_payload},
        )
        prediction_id = str(response.get("id") or "").strip()
        if not prediction_id:
            raise ValueError("Replicate did not return a prediction id")
        poll_url = str(response.get("url") or "").strip() or urljoin(
            self._base(base_url), f"predictions/{prediction_id}"
        )
        return ProviderJobRef(
            provider_type=self.provider_type,
            provider_job_id=prediction_id,
            polling_url=poll_url,
            cancel_supported=True,
        )

    async def poll(self, *, api_key: str, base_url: str | None, job: ProviderJobRef) -> ProviderJobSnapshot:
        response = await self._request(
            "GET", job.polling_url or urljoin(self._base(base_url), f"predictions/{job.provider_job_id}"), api_key
        )
        status = str(response.get("status") or "").lower()
        state = {
            "starting": "submitted",
            "processing": "running",
            "succeeded": "completed",
            "failed": "failed",
            "canceled": "cancelled",
            "cancelled": "cancelled",
        }.get(status, "running")
        output = response.get("output")
        asset_url = output if isinstance(output, str) else (output[0] if isinstance(output, list) and output else None)
        return ProviderJobSnapshot(
            state=state,
            provider_status=status or None,
            provider_job_id=job.provider_job_id,
            asset_url=str(asset_url) if asset_url else None,
            error_message=str(response.get("error") or "")[:2000] or None,
            raw=response,
        )

    async def cancel(self, *, api_key: str, base_url: str | None, job: ProviderJobRef) -> bool:
        url = urljoin(self._base(base_url), f"predictions/{job.provider_job_id}")
        response = await self._request("POST", url + "/cancel", api_key, allow_404=True)
        return bool(response is not None)

    async def fetch_result(
        self, *, api_key: str, base_url: str | None, snapshot: ProviderJobSnapshot
    ) -> ProviderAssetRef:
        if not snapshot.asset_url:
            raise ValueError("Replicate completed without an output URL")
        return ProviderAssetRef(
            url=snapshot.asset_url,
            mime_type="video/mp4",
            requires_auth=False,
            allowed_hosts=(),
        )

    def normalize_usage(self, snapshot: ProviderJobSnapshot) -> VideoUsage:
        metrics = snapshot.raw.get("metrics") if isinstance(snapshot.raw.get("metrics"), dict) else {}
        duration = metrics.get("predict_time") or snapshot.raw.get("duration")
        try:
            quantity = float(duration) if duration is not None else None
        except (TypeError, ValueError):
            quantity = None
        return VideoUsage(quantity=quantity, unit="second" if quantity else "clip", raw=snapshot.raw)

    async def _request(
        self,
        method: str,
        url: str,
        api_key: str,
        *,
        json_body: dict[str, Any] | None = None,
        allow_404: bool = False,
    ) -> dict[str, Any]:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("Invalid Replicate URL")
        # Replicate is the same async-job shape as OpenRouter -- one create,
        # then a status GET every few seconds -- so it pays the same price for
        # a fresh connection each time, and it used to build a whole new client
        # per request. The shared provider client keeps the connection and
        # retries the handshake.
        client = get_provider_rest_client()
        response = await client.request(
            method,
            url,
            headers=self._headers(api_key),
            json=json_body,
            follow_redirects=False,
            timeout=httpx.Timeout(get_settings().provider_http_timeout_seconds, connect=provider_connect_timeout()),
        )
        if allow_404 and response.status_code == 404:
            return {}
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("Replicate returned an invalid response")
        return payload
