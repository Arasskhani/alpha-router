"""Guardrails' detectors: the library, administrators' own patterns, and the limits that keep them safe."""

from __future__ import annotations

import time

import pytest

from app.services.guardrail_patterns import (
    LIBRARY,
    LIBRARY_BY_REF,
    PatternError,
    PatternSpec,
    TooManyMatches,
    check_samples,
    compile_pattern,
    find_all,
    hint,
    iban_ok,
    ir_national_code_ok,
    luhn_ok,
    normalize,
)


def values(spec: PatternSpec, text: str) -> list[str]:
    return [m.value for m in compile_pattern(spec).find(text)]


class TestTheLibrary:
    @pytest.mark.parametrize("spec", LIBRARY, ids=lambda s: s.ref)
    def test_each_entry_compiles_and_passes_its_own_samples(self, spec):
        assert check_samples(compile_pattern(spec)) == []

    def test_a_card_is_found_in_persian_digits_and_masked_where_it_was_written(self):
        text = "شماره کارت ۶۰۳۷-۹۹۱۸-۹۹۱۲-۳۴۵۳ است"
        (match,) = compile_pattern(LIBRARY_BY_REF["lib:bank_card"]).find(text)
        assert text[match.start : match.end] == "۶۰۳۷-۹۹۱۸-۹۹۱۲-۳۴۵۳"

    def test_a_number_that_fails_its_check_is_not_a_find(self):
        assert values(LIBRARY_BY_REF["lib:bank_card"], "order 1234 5678 9012 3456") == []
        assert values(LIBRARY_BY_REF["lib:ir_national_code"], "code 1111111111") == []

    def test_validators(self):
        assert luhn_ok("4111 1111 1111 1111") and not luhn_ok("4111 1111 1111 1112")
        assert iban_ok("IR062960000000100324200001") and not iban_ok("IR062960000000100324200002")
        assert ir_national_code_ok("0084575948") and not ir_national_code_ok("0084575949")


class TestAnAdministratorsPattern:
    def test_a_regex_with_context_and_never_match(self):
        spec = PatternSpec(
            ref="custom:1",
            name="Contract",
            expression=r"\bCNT-\d{4}-\d{5}\b",
            context_words=("قرارداد", "contract"),
            context_window=40,
            never_match=("CNT-0000-00000",),
        )
        text = "قرارداد CNT-۲۰۲۵-۱۰۴۴۲ و CNT-0000-00000; " + "x" * 80 + " CNT-2025-10443"
        assert values(spec, text) == ["CNT-۲۰۲۵-۱۰۴۴۲"]

    def test_a_word_list_finds_whole_words_in_any_script_and_spelling(self):
        spec = PatternSpec(ref="custom:2", name="Codenames", kind="words", entries=("Phoenix", "پروژه سیمرغ"))
        text = "about phoenix phoenix, Phoenix and پروژه‌ سيمرغ ok; phoenixes no"
        assert values(spec, text) == ["phoenix", "phoenix", "Phoenix", "پروژه‌ سيمرغ"]

    def test_case_sensitive_words(self):
        spec = PatternSpec(ref="custom:3", name="X", kind="words", entries=("ACME",), case_sensitive=True)
        assert values(spec, "acme and ACME") == ["ACME"]

    def test_domains_cover_subdomains_and_addresses_but_not_look_alikes(self):
        spec = PatternSpec(ref="custom:4", name="Ours", kind="domains", entries=("gosilkroad.net",))
        text = "a.b@gosilkroad.net, https://git.gosilkroad.net/x, gosilkroad.network, xgosilkroad.net"
        assert values(spec, text) == ["a.b@gosilkroad.net", "git.gosilkroad.net"]

    @pytest.mark.parametrize(
        ("expression", "reason"),
        [
            ("a*", "empty text"),
            (r"(a)\1", "Not a valid expression"),
            ("(?=x)y", "Not a valid expression"),
            ("(", "Not a valid expression"),
            ("x" * 1001, "at most 1000"),
        ],
    )
    def test_dangerous_or_broken_expressions_are_refused_with_the_reason(self, expression, reason):
        with pytest.raises(PatternError, match=reason):
            compile_pattern(PatternSpec(ref="x", name="x", expression=expression))

    def test_the_label_and_lists_are_checked(self):
        with pytest.raises(PatternError, match="redaction label"):
            compile_pattern(PatternSpec(ref="x", name="x", expression="abc", redact_label="bad label"))
        with pytest.raises(PatternError, match="at least one entry"):
            compile_pattern(PatternSpec(ref="x", name="x", kind="words", entries=(" ",)))

    def test_samples_say_what_is_wrong(self):
        spec = PatternSpec(
            ref="x", name="x", expression=r"\bAB\d\b", must_match=("AB1", "AB"), must_not_match=("ok", "AB2")
        )
        assert check_samples(compile_pattern(spec)) == [
            "Should match but does not: AB",
            "Should not match but does: AB2",
        ]


class TestTheEngine:
    def test_normalisation_maps_positions_back(self):
        view = normalize("a‌b۱")
        assert view.text == "ab1"
        assert view.span(1, 3) == (2, 4)

    def test_a_large_text_is_searched_quickly(self):
        patterns = [compile_pattern(spec) for spec in LIBRARY]
        text = "متن عادی فارسی بدون داده حساس " * 40_000
        started = time.perf_counter()
        assert find_all(patterns, text) == []
        assert time.perf_counter() - started < 5

    def test_a_find_on_a_window_boundary_is_found_once(self):
        from app.services import guardrail_patterns

        text = "x" * (guardrail_patterns.WINDOW_CHARS - 5) + " someone@example.com "
        assert values(LIBRARY_BY_REF["lib:email"], text) == ["someone@example.com"]

    def test_hints_never_show_the_value(self):
        assert hint("sk-proj-abcdefghijklmnop") == "sk-…nop"
        assert hint("0912345") == "0…5"
        assert hint("abc") == "•••"
        assert hint("password: hunter22", secret=True) == "••• (17 chars)"

    def test_a_text_with_nothing_to_drop_keeps_its_positions(self):
        view = normalize("کارت ۶۰۳۷ يك")
        assert view.text == "کارت 6037 یک"
        assert view.origin == () and view.span(5, 9) == (5, 9)

    def test_a_long_find_cut_by_a_window_is_masked_whole(self):
        from app.services import guardrail_patterns

        body = "A" * (guardrail_patterns.WINDOW_MARGIN * 2)
        key = f"-----BEGIN RSA PRIVATE KEY-----\n{body}\n-----END RSA PRIVATE KEY-----"
        text = "x" * (guardrail_patterns.WINDOW_CHARS - 10) + key + " tail"
        (found,) = compile_pattern(LIBRARY_BY_REF["lib:private_key"]).find(text)
        assert found.value == key

    def test_a_find_ending_at_a_window_edge_is_not_cut(self):
        from app.services import guardrail_patterns

        edge = guardrail_patterns.WINDOW_CHARS + guardrail_patterns.WINDOW_MARGIN
        email = "someone@example.com"
        # The first window ends after "someone@example.co": a find there, but not the whole address.
        before = edge - len("someone@example.co")
        text = "x" * (before - 1) + " " + email + " more"
        assert values(LIBRARY_BY_REF["lib:email"], text) == [email]

    def test_more_finds_than_allowed_stop_the_check(self, monkeypatch):
        from app.services import guardrail_patterns

        monkeypatch.setattr(guardrail_patterns, "MAX_MATCHES_PER_PATTERN", 3)
        with pytest.raises(TooManyMatches):
            compile_pattern(LIBRARY_BY_REF["lib:email"]).find("a@b.co c@d.co e@f.co g@h.co")
