"""Provider adapter registry for video generation."""

from __future__ import annotations

from collections.abc import Mapping

from app.services.video_providers.contracts import VideoProviderAdapter
from app.services.video_providers.openrouter import OpenRouterVideoAdapter
from app.services.video_providers.replicate import ReplicateVideoAdapter

_ADAPTERS: dict[str, VideoProviderAdapter] = {
    "openrouter": OpenRouterVideoAdapter(),
    "replicate": ReplicateVideoAdapter(),
}


def register_video_adapter(adapter: VideoProviderAdapter) -> None:
    key = (adapter.provider_type or "").strip().lower()
    if not key:
        raise ValueError("Video adapter provider_type is required")
    _ADAPTERS[key] = adapter


def get_video_adapter(provider_type: str, *, adapter_key: str | None = None) -> VideoProviderAdapter:
    key = (adapter_key or provider_type or "").strip().lower()
    try:
        return _ADAPTERS[key]
    except KeyError as exc:
        supported = ", ".join(sorted(_ADAPTERS))
        raise ValueError(f"Unsupported video provider '{key}'. Registered providers: {supported}") from exc


def registered_video_adapters() -> Mapping[str, VideoProviderAdapter]:
    return dict(_ADAPTERS)

