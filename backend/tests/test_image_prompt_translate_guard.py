"""Unit tests for translate failure paths in prompt enhance."""

import pytest

from app.services.image_prompt_service import PromptEnhanceError, _fail_or_fallback


def test_fail_or_fallback_raises_for_translate():
    with pytest.raises(PromptEnhanceError, match="budget"):
        _fail_or_fallback("translate", "budget limit", "اصلی")


def test_fail_or_fallback_returns_original_for_improve():
    assert _fail_or_fallback("improve", "budget limit", "اصلی") == "اصلی"
