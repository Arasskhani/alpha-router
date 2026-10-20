"""Guardrails: which rules apply to a text on its way out, and what they decide.

The rules are the administrator's; this module only applies them:

- A rule applies when it is on (``monitor`` or ``enforce``), watches the
  channel the text travels in and the trust level of where it is going, and
  its scope includes the person (or the owner of the API key) sending it.
- It matches when its patterns find enough: any pattern (or each of them,
  with ``all``), at least ``min_matches`` finds in all.
- Of the enforcing rules that match, the strictest action wins: ``block``
  over ``route`` over ``redact``. Masked values from every redacting rule are
  masked together. A ``monitor`` rule changes nothing and is only recorded.
- Masking replaces each value with a placeholder such as ``[CARD_1]``; the
  same value gets the same placeholder throughout a request, and the reply
  can be given its values back (``ReplyRestorer``) when the administrator
  wants it.

Events are written in a session of their own, so a request that is refused
still leaves its record.
"""

from __future__ import annotations

import asyncio
import dataclasses
import datetime
import json
import logging
import re
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.guardrail import GuardrailEvent, GuardrailPattern, GuardrailRule, GuardrailRuleAssignment
from app.models.system import SystemSetting
from app.services.guardrail_patterns import (
    CompiledPattern,
    Match,
    PatternError,
    PatternSpec,
    SECRET_REFS,
    compile_pattern,
    hint,
    library_pattern,
    normalize,
)
from app.services.resource_access_service import ResourceAccessSubject, evaluate_access

logger = logging.getLogger(__name__)

CHANNELS = ("chat", "attachments", "context", "extension", "gateway", "web_search", "web_fetch")
CHANNEL_LABELS = {
    "chat": "Chat messages",
    "attachments": "Attached files",
    "context": "Context the platform adds (memory, project files, knowledge)",
    "extension": "Browser extension",
    "gateway": "Gateway (API keys)",
    "web_search": "Web search queries",
    "web_fetch": "Web fetch addresses",
}
#: Channels where a text can be masked or sent elsewhere; an address or a query can only be stopped.
ROUTABLE_CHANNELS = frozenset({"chat", "attachments", "extension", "gateway"})
REDACTABLE_CHANNELS = frozenset({"chat", "attachments", "context", "extension", "gateway", "web_search"})

TRUST_LEVELS = ("internal", "trusted", "public")
TRUST_LABELS = {"internal": "Internal", "trusted": "Trusted external", "public": "Public"}
ACTIONS = ("block", "redact", "route")
MODES = ("off", "monitor", "enforce")
_STRICTNESS = {"redact": 1, "route": 2, "block": 3}

SETTINGS_KEY = "guardrails.settings"
VERSION_KEY = "guardrails.policy_version"

DEFAULT_MESSAGES = {
    "block": "This was not sent: it contains information your organisation does not allow to be sent here.",
    "redact": "Some details were masked before sending, as your organisation requires.",
    "route": "Answered by {model}, as your organisation requires.",
}

_PLACEHOLDER = re.compile(r"\[([A-Z][A-Z0-9_]{0,40})_(\d{1,5})\]")


class GuardrailBlocked(Exception):
    """A rule stopped the text. ``message`` is what the person is told."""

    def __init__(self, message: str, *, rule_id: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.rule_id = rule_id


class GuardrailEngineError(Exception):
    """The text could not be checked, and the administrator chose to stop what cannot be checked."""


# --- settings -------------------------------------------------------------------------------------------------


@dataclass
class GuardrailSettings:
    #: Stop a request when it cannot be checked (fail closed), or let it through and record why.
    fail_closed: bool = True
    #: Give masked values back to the person in the reply.
    restore_replies: bool = True
    event_retention_days: int = 180
    #: Addresses told when a rule blocks something.
    alert_emails: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "fail_closed": self.fail_closed,
            "restore_replies": self.restore_replies,
            "event_retention_days": self.event_retention_days,
            "alert_emails": list(self.alert_emails),
        }


async def load_settings(db: AsyncSession) -> GuardrailSettings:
    row = await db.get(SystemSetting, SETTINGS_KEY)
    try:
        data = json.loads(str(row.value)) if row is not None and row.value else {}
    except ValueError:
        data = {}
    defaults = GuardrailSettings()
    return GuardrailSettings(
        fail_closed=bool(data.get("fail_closed", defaults.fail_closed)),
        restore_replies=bool(data.get("restore_replies", defaults.restore_replies)),
        event_retention_days=int(data.get("event_retention_days", defaults.event_retention_days) or 180),
        alert_emails=[str(e) for e in data.get("alert_emails") or [] if str(e).strip()],
    )


async def save_settings(db: AsyncSession, settings: GuardrailSettings) -> None:
    value = json.dumps(settings.as_dict())
    row = await db.get(SystemSetting, SETTINGS_KEY)
    if row is None:
        db.add(SystemSetting(key=SETTINGS_KEY, value=value))
    else:
        row.value = value  # type: ignore[assignment]


# --- the policy -----------------------------------------------------------------------------------------------


def json_list(value: Any) -> list[Any]:
    try:
        data = json.loads(value) if isinstance(value, str) and value else []
    except ValueError:
        return []
    return data if isinstance(data, list) else []


def spec_from_row(row: GuardrailPattern) -> PatternSpec:
    return PatternSpec(
        ref=f"custom:{row.id}",
        name=str(row.name),
        kind=str(row.kind),
        expression=str(row.expression or ""),
        entries=tuple(str(v) for v in json_list(row.entries_json)),
        case_sensitive=bool(row.case_sensitive),
        normalize=bool(row.normalize),
        context_words=tuple(str(v) for v in json_list(row.context_words_json)),
        context_window=int(row.context_window or 0),
        validator=str(row.validator) if row.validator else None,
        never_match=tuple(str(v) for v in json_list(row.never_match_json)),
        redact_label=str(row.redact_label or "REDACTED"),
        description=str(row.description or ""),
        must_match=tuple(str(v) for v in json_list(row.must_match_json)),
        must_not_match=tuple(str(v) for v in json_list(row.must_not_match_json)),
    )


@dataclass
class Grant:
    """An assignment as evaluate_access reads it."""

    user_id: int | None
    group_id: int | None
    department: str | None
    role_slug: str | None
    effect: str


@dataclass
class CompiledRule:
    id: int
    name: str
    version: int
    mode: str
    patterns: list[CompiledPattern]
    match_mode: str
    min_matches: int
    channels: frozenset[str]
    destinations: frozenset[str]
    action: str
    route_model_id: int | None
    user_message: str
    access_type: str
    grants: list[Grant]
    #: Patterns the rule names that could not be used (deleted, or broken): the rule is not applied without them.
    broken: list[str] = field(default_factory=list)

    def applies_to(self, subject: ResourceAccessSubject) -> bool:
        # A request is checked whoever sends it: a key whose owner was deactivated still works, so an
        # inactive subject is matched like an active one rather than escaping every rule.
        if not subject.active:
            subject = dataclasses.replace(subject, active=True)
        return evaluate_access(access_type=self.access_type, assignments=self.grants, subject=subject)


@dataclass
class Policy:
    version: str
    rules: list[CompiledRule]

    @property
    def active(self) -> bool:
        return any(rule.mode != "off" for rule in self.rules)

    def watches(self, channel: str) -> bool:
        return any(rule.mode != "off" and channel in rule.channels for rule in self.rules)


_CACHE: dict[str, Policy] = {}


def reset_policy_cache() -> None:
    _CACHE.clear()


async def bump_policy_version(db: AsyncSession) -> None:
    """Say that the rules changed: every worker reloads them on its next request."""
    token = uuid.uuid4().hex
    row = await db.get(SystemSetting, VERSION_KEY)
    if row is None:
        db.add(SystemSetting(key=VERSION_KEY, value=token))
    else:
        row.value = token  # type: ignore[assignment]


async def load_policy(db: AsyncSession) -> Policy:
    """The rules as they stand, compiled; cached per worker until an administrator changes them."""
    row = await db.get(SystemSetting, VERSION_KEY)
    version = str(row.value) if row is not None and row.value else ""
    if version and version in _CACHE:
        return _CACHE[version]
    rules = (await db.execute(select(GuardrailRule).order_by(GuardrailRule.position, GuardrailRule.id))).scalars().all()
    policy = Policy(version=version, rules=[])
    if rules:
        patterns = {f"custom:{p.id}": p for p in (await db.execute(select(GuardrailPattern))).scalars().all()}
        grants: dict[int, list[Grant]] = {}
        for a in (await db.execute(select(GuardrailRuleAssignment))).scalars().all():
            grants.setdefault(int(a.rule_id), []).append(
                Grant(
                    user_id=int(a.user_id) if a.user_id is not None else None,
                    group_id=int(a.group_id) if a.group_id is not None else None,
                    department=str(a.department) if a.department else None,
                    role_slug=str(a.role_slug) if a.role_slug else None,
                    effect=str(a.effect or "allow"),
                )
            )
        policy.rules = [_compile_rule(rule, patterns, grants.get(int(rule.id), [])) for rule in rules]
    if version:
        _CACHE.clear()
        _CACHE[version] = policy
    return policy


def _compile_rule(rule: GuardrailRule, patterns: dict[str, GuardrailPattern], grants: list[Grant]) -> CompiledRule:
    compiled: list[CompiledPattern] = []
    broken: list[str] = []
    for ref in json_list(rule.patterns_json):
        ref = str(ref)
        spec = library_pattern(ref) if ref.startswith("lib:") else None
        if spec is None and ref in patterns:
            spec = spec_from_row(patterns[ref])
        if spec is None:
            broken.append(ref)
            continue
        try:
            compiled.append(compile_pattern(spec))
        except PatternError:
            broken.append(ref)
    return CompiledRule(
        id=int(rule.id),
        name=str(rule.name),
        version=int(rule.version or 1),
        mode=str(rule.mode or "off"),
        patterns=compiled,
        match_mode=str(rule.match_mode or "any"),
        min_matches=max(1, int(rule.min_matches or 1)),
        channels=frozenset(str(c) for c in json_list(rule.channels_json)),
        destinations=frozenset(str(d) for d in json_list(rule.destinations_json)),
        action=str(rule.action or "block"),
        route_model_id=int(rule.route_model_id) if rule.route_model_id is not None else None,
        user_message=str(rule.user_message or ""),
        access_type=str(rule.access_type or "public"),
        grants=grants,
        broken=broken,
    )


# --- what is inspected ----------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Destination:
    label: str
    trust: str = "public"
    connection_id: int | None = None
    model_id: int | None = None
    model_ref: str | None = None


@dataclass(frozen=True)
class Segment:
    """A stretch of text on its way out: where it sits, and which channel it travels in."""

    channel: str
    text: str
    #: Where it came from, to write a masked text back: message index, content part index, offset in that text.
    message: int | None = None
    part: int | None = None
    offset: int = 0


#: Where the first attached file begins: after the typed text, or at the start when nothing was typed.
_ATTACHMENT_NOTE = re.compile(r"(?:^|\n\n)--- [^\n]{1,300} ---\n")


def _text_parts(content: Any) -> list[tuple[int | None, str]]:
    if isinstance(content, str):
        return [(None, content)]
    if isinstance(content, list):
        return [
            (i, str(part.get("text") or ""))
            for i, part in enumerate(content)
            if isinstance(part, dict) and part.get("type") == "text" and part.get("text")
        ]
    return []


def message_segments(
    messages: Sequence[dict[str, Any]],
    *,
    channel: str,
    skip: Iterable[int] = (),
) -> list[Segment]:
    """The texts of ``messages`` as segments.

    ``channel`` is ``chat`` for the web chat - then what a person typed and the
    files they attached are told apart - or one channel for every text
    (``extension``, ``gateway``, ``context``).
    """
    skipped = set(skip)
    out: list[Segment] = []
    for index, message in enumerate(messages):
        if index in skipped:
            continue
        for part, text in _text_parts(message.get("content")):
            if channel == "chat" and message.get("role") == "user":
                note = _ATTACHMENT_NOTE.search(text)
                if note:
                    out.append(Segment("chat", text[: note.start()], index, part, 0))
                    out.append(Segment("attachments", text[note.start() :], index, part, note.start()))
                    continue
            out.append(Segment(channel, text, index, part, 0))
    return out


# --- deciding -------------------------------------------------------------------------------------------------


@dataclass
class RuleHit:
    rule: CompiledRule
    channel: str
    matches: list[tuple[Segment, Match]]
    #: What the hit does: the rule's action, or ``block`` for a route that cannot be taken here.
    action: str = ""

    def __post_init__(self) -> None:
        self.action = self.action or self.rule.action

    @property
    def message(self) -> str:
        if self.action != self.rule.action:
            return DEFAULT_MESSAGES[self.action]
        return self.rule.user_message or DEFAULT_MESSAGES[self.action]

    @property
    def count(self) -> int:
        return len(self.matches)

    def findings(self) -> list[dict[str, Any]]:
        names = {p.spec.ref: p.spec.name for p in self.rule.patterns}
        grouped: dict[str, list[str]] = {}
        for _, match in self.matches:
            grouped.setdefault(match.ref, []).append(hint(match.value, secret=match.ref in SECRET_REFS))
        return [
            {"ref": ref, "name": names.get(ref, ref), "count": len(hints), "hints": hints[:5]}
            for ref, hints in grouped.items()
        ]


@dataclass
class Verdict:
    """What the rules decided for one request."""

    action: str | None = None
    #: The rule that blocked, or routed.
    deciding: RuleHit | None = None
    enforced: list[RuleHit] = field(default_factory=list)
    monitored: list[RuleHit] = field(default_factory=list)
    #: The finds to mask (every enforcing redact rule's).
    to_mask: list[tuple[Segment, Match, str]] = field(default_factory=list)

    @property
    def blocked(self) -> bool:
        return self.action == "block"

    def applied(self, hit: RuleHit) -> bool:
        """Whether a matching enforcing rule's action was carried out (a stricter one may outrank it)."""
        action = hit.action
        if self.action == "block":
            return hit is self.deciding
        if self.action == "route":
            return hit is self.deciding or action == "redact"
        return action == "redact"

    def notices(self, model_label: str = "") -> list[str]:
        """What the person is told, one line per rule that changed their request."""
        return [item["message"] for item in self.notice_items(model_label)]

    def notice_items(self, model_label: str = "") -> list[dict[str, str]]:
        """``notices``, each with the action it tells of (block, redact or route), so it is shown as such."""
        out: list[dict[str, str]] = []
        for hit in self.enforced:
            if not self.applied(hit):
                continue
            message = hit.message.replace("{model}", model_label or "another model")
            if all(item["message"] != message for item in out):
                out.append({"action": hit.action, "message": message})
        return out

    def found_values(self) -> list[str]:
        """Every value any rule found - to keep out of what is stored - longest first."""
        values = {m.value for hit in [*self.enforced, *self.monitored] for _, m in hit.matches if m.value}
        return sorted(values, key=len, reverse=True)

    def secret_values(self) -> set[str]:
        """The found values that are secrets (keys, passwords): kept as their length only."""
        return {m.value for hit in [*self.enforced, *self.monitored] for _, m in hit.matches if m.ref in SECRET_REFS}


def decide(
    policy: Policy,
    segments: Sequence[Segment],
    *,
    destination: Destination,
    subject: ResourceAccessSubject,
    ignore_route_to: int | None = None,
    route_as_block: bool = False,
) -> Verdict:
    """Apply every rule to the segments; nothing is written and nothing changed.

    ``route_as_block``: the turn cannot be sent to another model here (an Agent's turn, a turn routed once
    already, the context added after the model was chosen), so a rule that would route it stops it instead.
    """
    verdict = Verdict()
    if not segments or not policy.active:
        return verdict
    cache: dict[tuple[int, str], list[Match]] = {}
    views: dict[int, Any] = {}
    for rule in policy.rules:
        if rule.mode == "off" or rule.broken or not rule.patterns:
            continue
        if rule.destinations and destination.trust not in rule.destinations:
            continue
        watched = [s for s in segments if s.channel in rule.channels]
        if not watched or not rule.applies_to(subject):
            continue
        if rule.action == "route" and (rule.route_model_id is None or rule.route_model_id == ignore_route_to):
            continue
        action = "block" if rule.action == "route" and route_as_block else rule.action
        found: list[tuple[Segment, Match]] = []
        for segment in watched:
            for pattern in rule.patterns:
                key = (id(segment), pattern.spec.ref)
                if key not in cache:
                    view = None
                    if pattern.spec.normalize:
                        # Made once per text, and only for the patterns that read the normalised form.
                        if id(segment) not in views:
                            views[id(segment)] = normalize(segment.text)
                        view = views[id(segment)]
                    cache[key] = pattern.find(segment.text, view)
                found.extend((segment, m) for m in cache[key])
        if not found:
            continue
        if rule.match_mode == "all" and {m.ref for _, m in found} != {p.spec.ref for p in rule.patterns}:
            continue
        if len(found) < rule.min_matches:
            continue
        hit = RuleHit(rule=rule, channel=_main_channel(found), matches=found, action=action)
        if rule.mode == "monitor":
            verdict.monitored.append(hit)
            continue
        verdict.enforced.append(hit)
        if action == "redact":
            labels = {p.spec.ref: p.spec.redact_label for p in rule.patterns}
            verdict.to_mask.extend((seg, m, labels.get(m.ref, "REDACTED")) for seg, m in found)
        current = _STRICTNESS.get(verdict.action or "", 0)
        if _STRICTNESS[action] > current:
            verdict.action = action
            if action in ("block", "route"):
                verdict.deciding = hit
    if verdict.action is None and verdict.to_mask:
        verdict.action = "redact"
    return verdict


def _main_channel(found: list[tuple[Segment, Match]]) -> str:
    counts: dict[str, int] = {}
    for segment, _ in found:
        counts[segment.channel] = counts.get(segment.channel, 0) + 1
    return max(counts, key=lambda c: counts[c])


# --- masking and giving back ----------------------------------------------------------------------------------


@dataclass
class Masker:
    """Placeholders for one request: the same value always gets the same one."""

    values: dict[str, str] = field(default_factory=dict)  # placeholder -> value
    _by_value: dict[tuple[str, str], str] = field(default_factory=dict)
    _counts: dict[str, int] = field(default_factory=dict)

    def placeholder(self, label: str, value: str) -> str:
        key = (label, value)
        if key not in self._by_value:
            self._counts[label] = self._counts.get(label, 0) + 1
            token = f"[{label}_{self._counts[label]}]"
            self._by_value[key] = token
            self.values[token] = value
        return self._by_value[key]

    def mask(self, text: str, finds: Iterable[tuple[int, int, str]]) -> str:
        """``text`` with each ``(start, end, label)`` find replaced; overlapping finds become one placeholder.

        Two finds that overlap are masked as their union, under the label of the one that starts first:
        no part of either is left in clear.
        """
        merged: list[list[Any]] = []
        for start, end, label in sorted(finds, key=lambda f: (f[0], -f[1])):
            if merged and start < merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], end)
                continue
            merged.append([start, end, label])
        out: list[str] = []
        cursor = 0
        for start, end, label in merged:
            out.append(text[cursor:start])
            out.append(self.placeholder(label, text[start:end]))
            cursor = end
        out.append(text[cursor:])
        return "".join(out)


def mask_messages(
    messages: list[dict[str, Any]], to_mask: Sequence[tuple[Segment, Match, str]], masker: Masker
) -> list[dict[str, Any]]:
    """A copy of ``messages`` with the finds masked where they were written."""
    by_text: dict[tuple[int, int | None], list[tuple[int, int, str]]] = {}
    for segment, match, label in to_mask:
        if segment.message is None:
            continue
        by_text.setdefault((segment.message, segment.part), []).append(
            (segment.offset + match.start, segment.offset + match.end, label)
        )
    out = list(messages)
    for (index, part), finds in by_text.items():
        message = dict(out[index])
        content = message.get("content")
        if part is None and isinstance(content, str):
            message["content"] = masker.mask(content, finds)
        elif part is not None and isinstance(content, list):
            parts = list(content)
            piece = dict(parts[part])
            piece["text"] = masker.mask(str(piece.get("text") or ""), finds)
            parts[part] = piece
            message["content"] = parts
        out[index] = message
    return out


def mask_text(text: str, to_mask: Sequence[tuple[Segment, Match, str]], masker: Masker) -> str:
    return masker.mask(text, [(m.start, m.end, label) for _, m, label in to_mask])


def redact_for_storage(text: str, values: Sequence[str], *, secret_values: Iterable[str] = ()) -> str:
    """``text`` with each found value replaced by its hint (``603…453``), as it is written or JSON-escaped.

    For what is kept of a refused message: the person still recognises it, the value itself is not stored.
    """
    secrets = set(secret_values)
    out = text
    for value in sorted(set(values), key=len, reverse=True):
        if not value:
            continue
        shown = hint(value, secret=value in secrets)
        out = out.replace(value, shown)
        escaped = json.dumps(value, ensure_ascii=False)[1:-1]
        if escaped != value:
            out = out.replace(escaped, json.dumps(shown, ensure_ascii=False)[1:-1])
    return out


def restore_text(text: str, values: dict[str, str]) -> str:
    if not values or "[" not in text:
        return text
    return _PLACEHOLDER.sub(lambda m: values.get(m.group(0), m.group(0)), text)


class ReplyRestorer:
    """Gives masked values back in a reply as it streams, holding back a placeholder cut between chunks."""

    #: The longest a placeholder can be; text after an unclosed ``[`` is held back at most this long.
    HOLD = 48

    def __init__(self, values: dict[str, str]) -> None:
        self.values = dict(values)
        self._held = ""

    def feed(self, delta: str) -> str:
        text = self._held + (delta or "")
        cut = text.rfind("[")
        if cut != -1 and "]" not in text[cut:] and len(text) - cut <= self.HOLD:
            self._held, text = text[cut:], text[:cut]
        else:
            self._held = ""
        return restore_text(text, self.values)

    def flush(self) -> str:
        text, self._held = self._held, ""
        return restore_text(text, self.values)


# --- events ---------------------------------------------------------------------------------------------------


@dataclass
class EventContext:
    user_id: int | None = None
    username: str | None = None
    alpha_router_api_key_id: int | None = None
    source: str | None = None


def events_for(
    verdict: Verdict, destination: Destination, ctx: EventContext, *, new_from: int | None = None
) -> list[GuardrailEvent]:
    """The events for a verdict.

    ``new_from``: the index of the first message new in this request. A find
    only in the conversation sent again is not recorded again - unless its rule
    blocked or routed the request, which is always recorded.
    """
    rows: list[GuardrailEvent] = []
    for hit, kind in [(h, "monitor") for h in verdict.monitored] + [(h, "enforce") for h in verdict.enforced]:
        if new_from is not None and not (kind == "enforce" and hit is verdict.deciding):
            fresh = [(seg, m) for seg, m in hit.matches if seg.message is None or seg.message >= new_from]
            if not fresh:
                continue
            hit = RuleHit(rule=hit.rule, channel=hit.channel, matches=fresh, action=hit.action)
        action = hit.action
        if kind == "enforce" and not verdict.applied(hit):
            # Outranked by a stricter rule: recorded as what it would have done.
            kind = "outranked"
        rows.append(
            GuardrailEvent(
                rule_id=hit.rule.id,
                rule_name=hit.rule.name[:120],
                rule_version=hit.rule.version,
                action="monitor" if kind in ("monitor", "outranked") else action,
                intended_action=action if kind in ("monitor", "outranked") else None,
                channel=hit.channel[:32],
                destination=destination.label[:160],
                destination_trust=destination.trust,
                connection_id=destination.connection_id,
                user_id=ctx.user_id,
                username=(ctx.username or "")[:255] or None,
                alpha_router_api_key_id=ctx.alpha_router_api_key_id,
                source=(ctx.source or "")[:32] or None,
                model_ref=(destination.model_ref or "")[:255] or None,
                match_count=hit.count,
                findings_json=json.dumps(hit.findings(), ensure_ascii=False),
                message=hit.message if kind == "enforce" else None,
            )
        )
    return rows


def engine_error_event(channel: str, destination: Destination, ctx: EventContext, detail: str) -> GuardrailEvent:
    return GuardrailEvent(
        action="engine_error",
        channel=channel[:32],
        destination=destination.label[:160],
        destination_trust=destination.trust,
        connection_id=destination.connection_id,
        user_id=ctx.user_id,
        username=(ctx.username or "")[:255] or None,
        alpha_router_api_key_id=ctx.alpha_router_api_key_id,
        source=(ctx.source or "")[:32] or None,
        model_ref=(destination.model_ref or "")[:255] or None,
        match_count=0,
        message=detail[:500],
    )


#: How long recording an event may wait for a row lock: the request being checked may hold one on a row the
#: event refers to (the person's, while their budget is held), and it is waiting for this very write.
EVENT_LOCK_TIMEOUT_MS = 1500
#: When a write had to give up, it is tried again later, once the request's own transaction has ended.
EVENT_RETRY_DELAYS_S = (2.0, 10.0, 30.0)
_pending_writes: set[asyncio.Task[None]] = set()


def _event_values(row: GuardrailEvent) -> dict[str, Any]:
    values = {
        column.key: getattr(row, column.key)
        for column in GuardrailEvent.__table__.columns
        if column.key != "id" and getattr(row, column.key, None) is not None
    }
    values.setdefault("created_at", datetime.datetime.utcnow())
    return values


async def _insert_events(values: list[dict[str, Any]], session_factory: Any) -> None:
    async with session_factory() as db:
        if db.get_bind().dialect.name == "postgresql":
            await db.execute(sql_text(f"SET LOCAL lock_timeout = '{int(EVENT_LOCK_TIMEOUT_MS)}ms'"))
        db.add_all([GuardrailEvent(**v) for v in values])
        await db.commit()


async def _retry_events(values: list[dict[str, Any]], rows: Sequence[GuardrailEvent], session_factory: Any) -> None:
    for delay in EVENT_RETRY_DELAYS_S:
        await asyncio.sleep(delay)
        try:
            await _insert_events(values, session_factory)
        except Exception:  # noqa: BLE001 -- tried again below, then given up with a log line
            continue
        from app.services.guardrail_alerts import alert_blocked

        await alert_blocked(rows, session_factory)
        return
    logger.error("Gave up recording %d guardrail event(s)", len(values))


async def write_events(rows: Sequence[GuardrailEvent], session_factory: Any = None) -> None:
    """Record events in a session of their own: a refused request still leaves its record.

    Never waits long: a write that cannot take its locks at once is tried again in the background.
    """
    if not rows:
        return
    if session_factory is None:
        from app.database import AsyncSessionLocal

        session_factory = AsyncSessionLocal
    values = [_event_values(row) for row in rows]
    try:
        await _insert_events(values, session_factory)
    except Exception:  # noqa: BLE001 -- the record failing must not change what the rules decided
        logger.warning("Could not record %d guardrail event(s) now; trying again shortly", len(rows), exc_info=True)
        task = asyncio.create_task(_retry_events(values, rows, session_factory))
        _pending_writes.add(task)
        task.add_done_callback(_pending_writes.discard)
        return
    from app.services.guardrail_alerts import alert_blocked

    await alert_blocked(rows, session_factory)


# --- the one call integrations make ---------------------------------------------------------------------------


async def inspect(
    db: AsyncSession,
    segments: Sequence[Segment],
    *,
    destination: Destination,
    ctx: EventContext,
    ignore_route_to: int | None = None,
    route_as_block: bool = False,
    session_factory: Any = None,
    new_from: int | None = None,
) -> Verdict:
    """Apply the rules to what is about to leave, record what they did, and say what they decided.

    Never raises for a rule's decision - the caller blocks, masks or routes as
    the verdict says. Raises GuardrailEngineError when the text could not be
    checked and the administrator chose to stop what cannot be checked.
    """
    if not segments:
        return Verdict()
    channel = segments[0].channel
    try:
        policy = await load_policy(db)
        if not policy.active or not any(policy.watches(s.channel) for s in segments):
            return Verdict()
        from app.services.resource_access_service import resolve_resource_access_subject

        subject = await resolve_resource_access_subject(
            db, user_id=ctx.user_id, alpha_router_api_key_id=ctx.alpha_router_api_key_id, source=ctx.source
        )
        verdict = decide(
            policy,
            segments,
            destination=destination,
            subject=subject,
            ignore_route_to=ignore_route_to,
            route_as_block=route_as_block,
        )
    except Exception as exc:  # noqa: BLE001 -- what the administrator chose for an unchecked text decides
        logger.exception("Guardrails could not check a %s text", channel)
        settings = await _settings_or_default(db)
        await write_events(
            [engine_error_event(channel, destination, ctx, f"{type(exc).__name__}: {exc}")], session_factory
        )
        if settings.fail_closed:
            raise GuardrailEngineError("Guardrails could not check this request, so it was not sent.") from exc
        return Verdict()
    await write_events(events_for(verdict, destination, ctx, new_from=new_from), session_factory)
    return verdict


async def _settings_or_default(db: AsyncSession) -> GuardrailSettings:
    try:
        return await load_settings(db)
    except Exception:  # noqa: BLE001 -- unreadable settings: the safe default, fail closed
        return GuardrailSettings()
