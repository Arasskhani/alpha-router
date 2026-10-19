"""Guardrails: what a pattern finds in a text, safely.

A pattern is either one of the built-in library entries (a bank card checked
with Luhn, an IBAN with mod 97, an Iranian national code with its check digit,
API keys...) or one an administrator wrote: a regular expression, a word list
or a list of domains. Nothing here decides what to do with a find - that is
the rules' job (``guardrail_policy``).

Safety first: administrators' expressions run on RE2 (``google-re2``), whose
time is linear in the text and which refuses the constructs that can
backtrack without end (back-references, look-arounds). An expression that
matches the empty string, or one longer than the limits, is refused when it is
saved, with the reason - a broken pattern never reaches a chat turn.

Persian text is normalised before it is searched, when the pattern asks:
Persian and Arabic-Indic digits become ASCII digits, Arabic yeh and kaf become
their Persian forms, and the zero-width non-joiner, tatweel and short vowels
are dropped. The positions of a find are mapped back to the original text, so
what is masked is exactly what the person wrote.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

import re2

PATTERN_KINDS = ("regex", "words", "domains")
VALIDATORS = ("luhn", "iban", "ir_national_code")

#: Limits on what an administrator may save.
MAX_EXPRESSION_CHARS = 1000
MAX_LIST_ENTRIES = 500
MAX_LIST_ENTRY_CHARS = 200
MAX_CONTEXT_WINDOW = 500
MAX_SAMPLES = 20
MAX_SAMPLE_CHARS = 2000
#: Texts are searched in windows this long, overlapping by the margin, so a find
#: on a boundary is still found once.
WINDOW_CHARS = 200_000
WINDOW_MARGIN = 4_000
#: The most finds kept per pattern per text: enough to mask a list, bounded for a huge paste.
MAX_MATCHES_PER_PATTERN = 5_000

_LABEL_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,30}$")


class TooManyMatches(RuntimeError):
    """More finds than a pattern may report: the text is not checked rather than checked in part."""


class PatternError(ValueError):
    """A pattern that cannot be saved, and why."""


# --- normalisation --------------------------------------------------------------------------------------------

_DIGITS = {
    **{ord(c): str(i) for i, c in enumerate("۰۱۲۳۴۵۶۷۸۹")},
    **{ord(c): str(i) for i, c in enumerate("٠١٢٣٤٥٦٧٨٩")},
}
_LETTERS = {ord("ي"): "ی", ord("ى"): "ی", ord("ك"): "ک", ord("ۀ"): "ه", ord("ة"): "ه"}
_DROPPED = frozenset(
    [0x200C, 0x200D, 0x200E, 0x200F, 0x0640, 0xFEFF]  # ZWNJ, ZWJ, LRM, RLM, tatweel, BOM
    + list(range(0x064B, 0x0660))  # short vowels and other combining marks
    + [0x0670]
)


@dataclass(frozen=True)
class NormalizedText:
    """A text as patterns search it, and where each of its characters came from."""

    original: str
    text: str
    #: ``origin[i]`` is the index in ``original`` of ``text[i]``; one more entry for the end.
    origin: tuple[int, ...]

    def span(self, start: int, end: int) -> tuple[int, int]:
        """The original text's span for ``text[start:end]``."""
        if not self.origin:
            return start, end
        first = self.origin[start] if start < len(self.origin) else len(self.original)
        last = self.origin[end - 1] + 1 if end > start else first
        return first, last


_TRANSLATE = {**_DIGITS, **_LETTERS}
_DROPPED_RE = re.compile("[" + "".join(re.escape(chr(c)) for c in sorted(_DROPPED)) + "]")


def normalize(text: str) -> NormalizedText:
    if not _DROPPED_RE.search(text):
        # Nothing dropped: every character keeps its place, so spans need no map (and C does the work).
        return NormalizedText(original=text, text=text.translate(_TRANSLATE), origin=())
    out: list[str] = []
    origin: list[int] = []
    for index, char in enumerate(text):
        code = ord(char)
        if code in _DROPPED:
            continue
        mapped = _DIGITS.get(code) or _LETTERS.get(code) or char
        out.append(mapped)
        origin.append(index)
    origin.append(len(text))
    return NormalizedText(original=text, text="".join(out), origin=tuple(origin))


def identity(text: str) -> NormalizedText:
    return NormalizedText(original=text, text=text, origin=())


def normal_value(value: str) -> str:
    """A value as ``never_match`` and context words compare it: normalised, case-folded, spaces collapsed."""
    return " ".join(normalize(value).text.casefold().split())


# --- validators -----------------------------------------------------------------------------------------------


def _digits(value: str) -> str:
    return "".join(c for c in value if c.isdigit())


def luhn_ok(value: str) -> bool:
    digits = _digits(value)
    if not 12 <= len(digits) <= 19 or len(set(digits)) == 1:
        return False
    total = 0
    for position, char in enumerate(reversed(digits)):
        number = int(char)
        if position % 2:
            number *= 2
            if number > 9:
                number -= 9
        total += number
    return total % 10 == 0


def iban_ok(value: str) -> bool:
    compact = "".join(value.split()).upper()
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{10,30}", compact):
        return False
    rearranged = compact[4:] + compact[:4]
    numeric = "".join(str(int(c, 36)) for c in rearranged)
    return int(numeric) % 97 == 1


def ir_national_code_ok(value: str) -> bool:
    digits = _digits(value)
    if len(digits) != 10 or len(set(digits)) == 1:
        return False
    check = int(digits[9])
    total = sum(int(digits[i]) * (10 - i) for i in range(9)) % 11
    return check == total if total < 2 else check == 11 - total


VALIDATOR_FUNCTIONS: dict[str, Callable[[str], bool]] = {
    "luhn": luhn_ok,
    "iban": iban_ok,
    "ir_national_code": ir_national_code_ok,
}
VALIDATOR_LABELS = {
    "luhn": "Card checksum (Luhn)",
    "iban": "IBAN checksum (mod 97)",
    "ir_national_code": "Iranian national code check digit",
}


# --- patterns -------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class PatternSpec:
    """What a pattern looks for; the same shape for a library entry and an administrator's own."""

    ref: str
    name: str
    kind: str = "regex"
    expression: str = ""
    entries: tuple[str, ...] = ()
    case_sensitive: bool = False
    normalize: bool = True
    context_words: tuple[str, ...] = ()
    context_window: int = 50
    validator: str | None = None
    never_match: tuple[str, ...] = ()
    redact_label: str = "REDACTED"
    description: str = ""
    must_match: tuple[str, ...] = ()
    must_not_match: tuple[str, ...] = ()


@dataclass(frozen=True)
class Match:
    ref: str
    start: int
    end: int
    value: str


def _options() -> Any:
    options = re2.Options()
    options.log_errors = False
    return options


def _source(spec: PatternSpec) -> str:
    """The RE2 expression a spec searches with; a list's word edges are checked after the search."""
    flags = "" if spec.case_sensitive else "(?i)"
    if spec.kind == "regex":
        return f"{flags}(?:{spec.expression})"
    entries = [_entry(e, spec) for e in spec.entries if e.strip()]
    if not entries:
        raise PatternError("Add at least one entry.")
    escaped = "|".join(re2.escape(e) for e in sorted(set(entries), key=len, reverse=True))
    if spec.kind == "words":
        # Whole words in any script: the edges are checked after the search (RE2's \b knows only ASCII letters).
        return f"{flags}({escaped})"
    # Domains: the domain, any subdomain of it, and an email address at it.
    return f"(?i)((?:[a-z0-9._%+-]+@)?(?:[a-z0-9-]+\\.)*(?:{escaped}))"


def _is_word_char(char: str) -> bool:
    return char.isalnum() or char == "_"


def _edges_ok(kind: str, text: str, start: int, end: int) -> bool:
    before = text[start - 1] if start > 0 else ""
    after = text[end] if end < len(text) else ""
    if kind == "words":
        return not (before and _is_word_char(before)) and not (after and _is_word_char(after))
    if kind == "domains":
        return not (before and (before.isascii() and (before.isalnum() or before in ".@_%+-"))) and not (
            after and after.isascii() and (after.isalnum() or after == "-")
        )
    return True


def _entry(entry: str, spec: PatternSpec) -> str:
    text = " ".join((normalize(entry).text if spec.normalize else entry).split())
    return text if spec.case_sensitive else text.casefold()


@lru_cache(maxsize=512)
def _compiled(source: str) -> Any:
    try:
        return re2.compile(source, _options())
    except re2.error as exc:
        detail = exc.args[0] if exc.args else exc
        if isinstance(detail, bytes):
            detail = detail.decode("utf-8", "replace")
        raise PatternError(f"Not a valid expression: {detail}.") from None


@dataclass
class CompiledPattern:
    spec: PatternSpec
    regex: Any = field(repr=False)

    def find(self, text: str, normalized: NormalizedText | None = None) -> list[Match]:
        """The finds in ``text``; ``normalized`` is its normalised form when the caller already made it."""
        if not text:
            return []
        if self.spec.normalize:
            view = normalized if normalized is not None and normalized.original is text else normalize(text)
        else:
            view = identity(text)
        never = {normal_value(v) for v in self.spec.never_match}
        context = [normal_value(w) for w in self.spec.context_words if w.strip()]
        validate = VALIDATOR_FUNCTIONS.get(self.spec.validator or "")
        found: dict[tuple[int, int], Match] = {}
        covered = 0  # where the finds of the earlier windows end: a find starting before it is one of theirs
        for offset in range(0, max(len(view.text), 1), WINDOW_CHARS):
            chunk = view.text[offset : offset + WINDOW_CHARS + WINDOW_MARGIN]
            window_covered = covered
            # One pass over each window: RE2 reads the text once, whatever the number of finds.
            last_window = offset + len(chunk) >= len(view.text)
            for match in self.regex.finditer(chunk):
                start, end = (offset + match.start(), offset + match.end())
                if not last_window and match.end() == len(chunk):
                    # It may go on past this window: the next one sees it whole, or it is read on from here.
                    if start >= offset + WINDOW_CHARS:
                        continue
                    longer = self.regex.match(view.text[start : start + WINDOW_CHARS + WINDOW_MARGIN])
                    if longer is not None:
                        end = start + longer.end()
                if end <= start or start < window_covered or not _edges_ok(self.spec.kind, view.text, start, end):
                    continue
                value_norm = view.text[start:end]
                if validate is not None and not validate(value_norm):
                    continue
                if never and normal_value(value_norm) in never:
                    continue
                if context and not self._near(view.text, start, end, context):
                    continue
                covered = max(covered, end)
                if len(found) >= MAX_MATCHES_PER_PATTERN:
                    raise TooManyMatches(f"{self.spec.name}: more than {MAX_MATCHES_PER_PATTERN} finds in one text.")
                o_start, o_end = view.span(start, end)
                found.setdefault((o_start, o_end), Match(self.spec.ref, o_start, o_end, text[o_start:o_end]))
        return sorted(found.values(), key=lambda m: (m.start, m.end))

    def _near(self, text: str, start: int, end: int, words: Sequence[str]) -> bool:
        window = max(0, min(self.spec.context_window, MAX_CONTEXT_WINDOW))
        around = text[max(0, start - window) : end + window].casefold()
        return any(word in around for word in words)


def compile_pattern(spec: PatternSpec) -> CompiledPattern:
    """A pattern ready to search; raises PatternError when it may not be used."""
    check_spec(spec)
    regex = _compiled(_source(spec))
    if spec.kind == "regex" and regex.fullmatch("") is not None:
        raise PatternError("The expression matches an empty text, so it would match everywhere.")
    return CompiledPattern(spec=spec, regex=regex)


def check_spec(spec: PatternSpec) -> None:
    if spec.kind not in PATTERN_KINDS:
        raise PatternError("Kind must be regex, words or domains.")
    if spec.kind == "regex":
        if not spec.expression.strip():
            raise PatternError("Enter an expression.")
        if len(spec.expression) > MAX_EXPRESSION_CHARS:
            raise PatternError(f"An expression may be at most {MAX_EXPRESSION_CHARS} characters.")
    else:
        if len(spec.entries) > MAX_LIST_ENTRIES:
            raise PatternError(f"A list may hold at most {MAX_LIST_ENTRIES} entries.")
        if any(len(e) > MAX_LIST_ENTRY_CHARS for e in spec.entries):
            raise PatternError(f"An entry may be at most {MAX_LIST_ENTRY_CHARS} characters.")
    if spec.validator and spec.validator not in VALIDATORS:
        raise PatternError("Unknown validator.")
    if not _LABEL_RE.match(spec.redact_label or ""):
        raise PatternError("The redaction label must be capital letters, digits and _ (e.g. CONTRACT).")
    if not 0 <= spec.context_window <= MAX_CONTEXT_WINDOW:
        raise PatternError(f"The context distance must be 0 to {MAX_CONTEXT_WINDOW} characters.")
    for name, values in (("never-match values", spec.never_match), ("context words", spec.context_words)):
        if len(values) > MAX_LIST_ENTRIES or any(len(v) > MAX_LIST_ENTRY_CHARS for v in values):
            raise PatternError(f"Too many or too long {name}.")
    for samples in (spec.must_match, spec.must_not_match):
        if len(samples) > MAX_SAMPLES or any(len(s) > MAX_SAMPLE_CHARS for s in samples):
            raise PatternError(f"At most {MAX_SAMPLES} samples of {MAX_SAMPLE_CHARS} characters each.")


def check_samples(compiled: CompiledPattern) -> list[str]:
    """The test samples a pattern gets wrong, said plainly; empty when it gets them all right."""
    problems: list[str] = []
    for sample in compiled.spec.must_match:
        if not compiled.find(sample):
            problems.append(f"Should match but does not: {sample[:80]}")
    for sample in compiled.spec.must_not_match:
        if compiled.find(sample):
            problems.append(f"Should not match but does: {sample[:80]}")
    return problems


#: Library patterns whose finds are secrets: events show only their length, never a character of them.
SECRET_REFS = frozenset(
    {
        "lib:openai_key",
        "lib:aws_key",
        "lib:github_token",
        "lib:google_key",
        "lib:private_key",
        "lib:jwt",
        "lib:password",
        "lib:connection_string",
    }
)


def hint(value: str, *, secret: bool = False) -> str:
    """A find as events show it: never the value, only enough to recognise its kind."""
    compact = "".join(value.split())
    if secret:
        return f"••• ({len(compact)} chars)"
    if len(compact) >= 12:
        return f"{compact[:3]}…{compact[-3:]}"
    if len(compact) >= 6:
        return f"{compact[:1]}…{compact[-1:]}"
    return "•••"


# --- the library ----------------------------------------------------------------------------------------------

LIBRARY: tuple[PatternSpec, ...] = (
    PatternSpec(
        ref="lib:bank_card",
        name="Bank card",
        description="Card numbers of 13-19 digits, spaces or dashes allowed, checked with Luhn (Shetab cards included).",
        expression=r"\b(?:\d[ -]?){12,18}\d\b",
        validator="luhn",
        redact_label="CARD",
        must_match=("6037 9918 9912 3453",),
        must_not_match=("1234 5678 9012 3456",),
    ),
    PatternSpec(
        ref="lib:iban",
        name="IBAN (Sheba)",
        description="IBANs such as IR06 0120 0000 0000 0123 4567 89, checked with mod 97.",
        expression=r"\b[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]{4}){3,7}(?:[ ]?[A-Z0-9]{1,4})?\b",
        validator="iban",
        redact_label="IBAN",
        must_match=("IR062960000000100324200001",),
        must_not_match=("IR062960000000100324200002",),
    ),
    PatternSpec(
        ref="lib:ir_national_code",
        name="Iranian national code",
        description="Ten-digit national codes, with their check digit validated.",
        expression=r"\b\d{3}-?\d{6}-?\d\b",
        validator="ir_national_code",
        redact_label="NATIONAL_ID",
        must_match=("0084575948",),
        must_not_match=("0084575949",),
    ),
    PatternSpec(
        ref="lib:ir_mobile",
        name="Iranian mobile number",
        description="09xx xxx xxxx, +98 9xx… and 0098 9xx…",
        expression=r"(?:\+98|\b0098|\b0)[ -]?9\d{2}[ -]?\d{3}[ -]?\d{4}\b",
        redact_label="MOBILE",
        must_match=("0912 345 6789", "+989123456789"),
        must_not_match=("021 8888 7777",),
    ),
    PatternSpec(
        ref="lib:email",
        name="Email address",
        expression=r"\b[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}\b",
        redact_label="EMAIL",
        must_match=("someone@example.com",),
        must_not_match=("not an @ address",),
    ),
    PatternSpec(
        ref="lib:ipv4",
        name="IPv4 address",
        expression=r"\b(?:(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\.){3}(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\b",
        redact_label="IP",
        must_match=("10.20.30.40",),
        must_not_match=("version 1.2.3",),
    ),
    PatternSpec(
        ref="lib:openai_key",
        name="OpenAI or Anthropic API key",
        expression=r"\bsk-(?:proj-|svcacct-|admin-|ant-)?[A-Za-z0-9_-]{20,}",
        case_sensitive=True,
        normalize=False,
        redact_label="API_KEY",
        must_match=("sk-proj-abcdefghijklmnopqrstuvwxyz0123",),
        must_not_match=("sk-short",),
    ),
    PatternSpec(
        ref="lib:aws_key",
        name="AWS access key",
        expression=r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b",
        case_sensitive=True,
        normalize=False,
        redact_label="API_KEY",
        must_match=("AKIAIOSFODNN7EXAMPLE",),
    ),
    PatternSpec(
        ref="lib:github_token",
        name="GitHub token",
        expression=r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{50,})",
        case_sensitive=True,
        normalize=False,
        redact_label="API_KEY",
        must_match=("ghp_" + "a" * 36,),
    ),
    PatternSpec(
        ref="lib:google_key",
        name="Google API key",
        expression=r"\bAIza[0-9A-Za-z_-]{35}",
        case_sensitive=True,
        normalize=False,
        redact_label="API_KEY",
        must_match=("AIza" + "B" * 35,),
    ),
    PatternSpec(
        ref="lib:private_key",
        name="Private key",
        description="A PEM private key block, from its BEGIN line to its END line.",
        expression=r"(?s)-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)",
        case_sensitive=True,
        normalize=False,
        redact_label="PRIVATE_KEY",
        must_match=("-----BEGIN RSA PRIVATE KEY-----\nMIIE\n-----END RSA PRIVATE KEY-----",),
    ),
    PatternSpec(
        ref="lib:jwt",
        name="JSON Web Token",
        expression=r"\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}",
        case_sensitive=True,
        normalize=False,
        redact_label="TOKEN",
        must_match=("eyJhbGciOiJI.eyJzdWIiOiIx.SflKxwRJSMeKKF2QT4",),
    ),
    PatternSpec(
        ref="lib:password",
        name="Password written out",
        description="password: …, pwd=…, رمز: … and the like.",
        expression=r"(?:password|passwd|pwd|passcode|رمز عبور|رمز|پسورد|کلمه عبور)\s*[:=]\s*\S{4,}",
        redact_label="PASSWORD",
        must_match=("password: hunter22", "رمز: abc12345"),
        must_not_match=("forgot my password again",),
    ),
    PatternSpec(
        ref="lib:connection_string",
        name="Database connection string",
        expression=r"\b(?:postgres(?:ql)?|mysql|mariadb|mongodb(?:\+srv)?|redis|amqp|mssql)://[^\s:@/]+:[^\s@/]+@[^\s/]+",
        redact_label="CONNECTION",
        must_match=("postgresql://app:s3cret@db.internal:5432/main",),
    ),
)

LIBRARY_BY_REF: dict[str, PatternSpec] = {spec.ref: spec for spec in LIBRARY}


def library_pattern(ref: str) -> PatternSpec | None:
    return LIBRARY_BY_REF.get(ref)


def find_all(patterns: Iterable[CompiledPattern], text: str) -> list[Match]:
    """Every pattern's finds in one text, normalised once for all of them."""
    patterns = list(patterns)
    if not text or not patterns:
        return []
    normalized = normalize(text) if any(p.spec.normalize for p in patterns) else None
    out: list[Match] = []
    for pattern in patterns:
        out.extend(pattern.find(text, normalized))
    return out
