"""Sandbox filename policy: any script is allowed, deception is not."""

from __future__ import annotations

import unicodedata

import pytest

from app.sandbox.filenames import (
    MAX_FILENAME_BYTES,
    MAX_FILENAME_CHARS,
    is_safe_filename,
    normalize_filename,
    scrub_filename_chars,
)


@pytest.mark.parametrize(
    "name",
    [
        "report.pdf",
        "گزارش-مدیریتی.pdf",
        "خلاصه‌فاکتورها.csv",  # contains U+200C (ZWNJ)
        "تحلیل هزینه (۱).pdf",
        "отчет.csv",
        "分析結果.json",
        "summary_2026.md",
        "report (1).pdf",
    ],
)
def test_names_in_any_script_are_accepted(name):
    assert is_safe_filename(unicodedata.normalize("NFC", name))


@pytest.mark.parametrize(
    "name",
    [
        "",
        ".",
        "..",
        ".hidden.pdf",
        "-flag.pdf",
        "sub/report.pdf",
        "sub\\report.pdf",
        "../../etc/passwd",
        "report\x00.pdf",
        "report\n.pdf",
        "report\t.pdf",
        "report .",
        "trailing.pdf ",
        " leading.pdf",
    ],
)
def test_traversal_control_and_hidden_names_are_rejected(name):
    assert not is_safe_filename(name)


@pytest.mark.parametrize(
    "name",
    [
        "report\u202efdp.exe.pdf",  # right-to-left override hides the real suffix
        "report\u200bhidden.pdf",  # zero-width space
        "report\u2066spoof.pdf",  # left-to-right isolate
        "report\ufeff.pdf",  # byte order mark
    ],
)
def test_bidi_and_zero_width_spoofing_is_rejected(name):
    assert not is_safe_filename(name)


def test_persian_zero_width_non_joiner_stays_allowed():
    assert is_safe_filename("نیم‌فاصله.pdf")


def test_only_the_nfc_spelling_is_accepted():
    decomposed = unicodedata.normalize("NFD", "résumé.pdf")
    assert not is_safe_filename(decomposed)
    assert is_safe_filename(normalize_filename(decomposed))


def test_length_budget_counts_characters_and_utf8_bytes():
    assert is_safe_filename(f"{'a' * (MAX_FILENAME_CHARS - 4)}.pdf")
    assert not is_safe_filename(f"{'a' * MAX_FILENAME_CHARS}.pdf")
    # CJK characters cost three bytes each, so the byte budget binds first.
    long_cjk = "分" * ((MAX_FILENAME_BYTES // 3) + 1)
    assert len(f"{long_cjk}.pdf") <= MAX_FILENAME_CHARS
    assert not is_safe_filename(f"{long_cjk}.pdf")


def test_scrub_folds_only_disallowed_characters():
    assert scrub_filename_chars("گزارش/نهایی") == "گزارش_نهایی"
    assert scrub_filename_chars("report\u202ex") == "report_x"
    assert scrub_filename_chars("گزارش نهایی (۱)") == "گزارش نهایی (۱)"
