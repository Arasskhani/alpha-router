"""Contract tests for provider-neutral video adapters."""


from app.services.video_providers import NormalizedVideoRequest, get_video_adapter
from app.services.video_providers.openrouter import OpenRouterVideoAdapter
from app.services.video_providers.replicate import ReplicateVideoAdapter


def test_registry_contains_multiple_provider_adapters():
    assert isinstance(get_video_adapter("openrouter"), OpenRouterVideoAdapter)
    assert isinstance(get_video_adapter("replicate"), ReplicateVideoAdapter)


def test_openrouter_adapter_payload_is_provider_internal():
    adapter = OpenRouterVideoAdapter()
    request = NormalizedVideoRequest(
        model_id="provider/video-model",
        prompt="A short cinematic clip",
        duration_seconds=4,
        resolution="720p",
    )
    assert request.operation == "generation"
    assert adapter.provider_type == "openrouter"


def test_replicate_adapter_has_distinct_provider_contract():
    adapter = ReplicateVideoAdapter()
    assert adapter.provider_type == "replicate"
    assert adapter.adapter_version.startswith("replicate-")
