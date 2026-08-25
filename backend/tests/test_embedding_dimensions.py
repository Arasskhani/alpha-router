from app.services.knowledge_embedding_service import suggested_embedding_dimensions
from app.services.memory_embedding_service import resolved_memory_embedding_dimensions


def test_suggested_embedding_dimensions_maps_known_models() -> None:
    assert suggested_embedding_dimensions("openai/text-embedding-3-large") == 3072
    assert suggested_embedding_dimensions("text-embedding-3-small") == 1536
    assert suggested_embedding_dimensions("text-embedding-ada-002") == 1536
    assert suggested_embedding_dimensions("google/gemini-embedding-001") == 3072
    assert suggested_embedding_dimensions("qwen3-embedding-8b") == 4096
    assert suggested_embedding_dimensions("qwen3-embedding-4b") == 2560
    assert suggested_embedding_dimensions("mistral-embed") == 1024
    assert suggested_embedding_dimensions("unknown-embedder") == 1536


def test_resolved_memory_embedding_dimensions_keeps_admin_override() -> None:
    assert (
        resolved_memory_embedding_dimensions(
            {"embedding_dimensions": 512},
            "text-embedding-3-small",
        )
        == 512
    )


def test_resolved_memory_embedding_dimensions_fills_from_model_when_unset() -> None:
    assert (
        resolved_memory_embedding_dimensions(
            {"embedding_dimensions": None},
            "google/gemini-embedding-001",
        )
        == 3072
    )
    assert (
        resolved_memory_embedding_dimensions(
            {"embedding_dimensions": 0},
            "text-embedding-3-large",
        )
        == 3072
    )
