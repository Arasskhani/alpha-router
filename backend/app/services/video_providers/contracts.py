"""Provider-neutral contracts for asynchronous video generation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


VideoState = str


@dataclass(frozen=True)
class NormalizedVideoRequest:
    model_id: str
    prompt: str
    operation: str = "generation"
    duration_seconds: int | None = None
    resolution: str | None = None
    aspect_ratio: str | None = None
    generate_audio: bool = False
    seed: int | None = None
    reference_image: bytes | None = None
    reference_image_mime: str | None = None
    routing: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class VideoCapabilities:
    supports_text_to_video: bool
    supports_image_to_video: bool
    supported_durations: tuple[int, ...] = ()
    supported_resolutions: tuple[str, ...] = ()
    supported_aspect_ratios: tuple[str, ...] = ()
    supported_frame_images: tuple[str, ...] = ()
    supports_audio: bool = False
    pricing_units: tuple[str, ...] = ("clip",)
    schema_version: str = "video-capabilities.v1"


@dataclass(frozen=True)
class ProviderJobRef:
    provider_type: str
    provider_job_id: str
    polling_url: str | None = None
    cancel_supported: bool = False


@dataclass(frozen=True)
class ProviderJobSnapshot:
    state: VideoState
    provider_status: str | None = None
    provider_job_id: str | None = None
    asset_url: str | None = None
    asset_mime: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderAssetRef:
    url: str
    mime_type: str | None = None
    requires_auth: bool = False
    allowed_hosts: tuple[str, ...] = ()


@dataclass(frozen=True)
class VideoUsage:
    quantity: float | None
    unit: str | None
    cost_usd: float | None = None
    raw: dict[str, Any] = field(default_factory=dict)


class VideoProviderAdapter(Protocol):
    """The only upstream contract used by the video orchestrator."""

    provider_type: str
    adapter_version: str

    async def submit(
        self,
        *,
        api_key: str,
        base_url: str | None,
        request: NormalizedVideoRequest,
    ) -> ProviderJobRef:
        ...

    async def poll(
        self,
        *,
        api_key: str,
        base_url: str | None,
        job: ProviderJobRef,
    ) -> ProviderJobSnapshot:
        ...

    async def cancel(
        self,
        *,
        api_key: str,
        base_url: str | None,
        job: ProviderJobRef,
    ) -> bool:
        ...

    async def fetch_result(
        self,
        *,
        api_key: str,
        base_url: str | None,
        snapshot: ProviderJobSnapshot,
    ) -> ProviderAssetRef:
        ...

    def normalize_usage(self, snapshot: ProviderJobSnapshot) -> VideoUsage:
        ...

