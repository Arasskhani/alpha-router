"""Provider-neutral video generation adapters."""

from app.services.video_providers.contracts import (
    NormalizedVideoRequest,
    ProviderAssetRef,
    ProviderJobRef,
    ProviderJobSnapshot,
    VideoCapabilities,
    VideoProviderAdapter,
    VideoUsage,
)
from app.services.video_providers.registry import (
    get_video_adapter,
    register_video_adapter,
    registered_video_adapters,
)

__all__ = [
    "NormalizedVideoRequest",
    "ProviderAssetRef",
    "ProviderJobRef",
    "ProviderJobSnapshot",
    "VideoCapabilities",
    "VideoProviderAdapter",
    "VideoUsage",
    "get_video_adapter",
    "register_video_adapter",
    "registered_video_adapters",
]

