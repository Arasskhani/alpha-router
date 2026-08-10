"""Chat completions reject models that cannot produce text replies."""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.services.model_capabilities import model_kinds
from app.services.proxy_service import assert_model_supports_text_chat


def test_rerank_only_model_has_no_text_kind():
    kinds = model_kinds(
        external_id="mongodb/voyage-3-large",
        pricing_raw='{"architecture":{"input_modalities":["text"],"output_modalities":["rerank"]}}',
        provider_type="openrouter",
    )
    assert "rerank" in kinds
    assert "text" not in kinds


def test_assert_model_supports_text_chat_rejects_rerank_only():
    model = SimpleNamespace(
        external_id="mongodb/voyage-rerank-2",
        is_image_model=False,
        is_video_model=False,
        pricing_raw='{"architecture":{"input_modalities":["text"],"output_modalities":["rerank"]}}',
        provider_type="openrouter",
    )
    with pytest.raises(HTTPException) as exc:
        assert_model_supports_text_chat(model)
    assert exc.value.status_code == 400
    detail = exc.value.detail
    assert isinstance(detail, dict)
    assert detail["code"] == "model_not_for_chat"


def test_assert_model_supports_text_chat_allows_text_models():
    model = SimpleNamespace(
        external_id="~deepseek/deepseek-v4-flash-latest",
        is_image_model=False,
        is_video_model=False,
        pricing_raw='{"architecture":{"input_modalities":["text"],"output_modalities":["text"]}}',
        provider_type="openrouter",
    )
    assert_model_supports_text_chat(model)
