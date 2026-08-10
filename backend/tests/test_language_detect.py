"""Tests for prompt language / translation heuristics."""

from app.core.language_detect import detect_prompt_language, needs_english_translation


def test_persian_needs_translation():
    assert needs_english_translation("سلام دنیا") is True
    assert detect_prompt_language("سلام دنیا") == "fa"


def test_english_does_not_need_translation():
    assert needs_english_translation("Hello world, please summarize this.") is False
    assert detect_prompt_language("Hello world") == "en"


def test_chinese_needs_translation_not_treated_as_english():
    text = "请把这段话总结一下"
    assert needs_english_translation(text) is True
    assert detect_prompt_language(text) == "other"


def test_empty_unknown():
    assert needs_english_translation("   ") is False
    assert detect_prompt_language("") == "unknown"
