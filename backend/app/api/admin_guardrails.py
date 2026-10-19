"""Admin: Guardrails - the patterns, the rules, who they apply to, where data may go, and what they did.

Every rule and pattern is the administrator's; nothing here creates one on its
own. Each change is written to the administrative trail and bumps the policy
version, so every worker applies it on its next request.
"""

from __future__ import annotations

import csv
import datetime
import io
import json
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_guardrails, require_guardrails_write
from app.database import get_db
from app.models.connection import Connection
from app.models.guardrail import GuardrailEvent, GuardrailPattern, GuardrailRule, GuardrailRuleAssignment
from app.models.model_catalog import AIModel
from app.models.user import User
from app.services.client_ip import resolve_client_ip
from app.services.connection_kinds import CONNECTION_KIND_MODELS, CONNECTION_KIND_WEB_SEARCH
from app.services.guardrail_patterns import (
    LIBRARY,
    PATTERN_KINDS,
    VALIDATOR_LABELS,
    PatternError,
    PatternSpec,
    check_samples,
    compile_pattern,
    library_pattern,
)
from app.services.guardrail_policy import (
    ACTIONS,
    CHANNEL_LABELS,
    CHANNELS,
    DEFAULT_MESSAGES,
    MODES,
    REDACTABLE_CHANNELS,
    ROUTABLE_CHANNELS,
    TRUST_LABELS,
    TRUST_LEVELS,
    Destination,
    GuardrailSettings,
    Masker,
    Policy,
    bump_policy_version,
    decide,
    json_list,
    load_policy,
    load_settings,
    mask_text,
    save_settings,
    spec_from_row,
)
from app.services.rate_limit import check_rate_limit
from app.services.resource_access_service import (
    VALID_ACCESS_TYPES,
    AccessGrant,
    ResourceAccessSubject,
    resolve_resource_access_subject,
    validated_grants,
)
from app.services.security_audit import log_security_event

router = APIRouter(prefix="/api/admin/guardrails", tags=["admin"])

#: Tries an administrator may run a minute (pattern tests and Test a text): cheap, but not unbounded.
TESTS_PER_MINUTE = 120
MAX_TEST_TEXT = 50_000
EXPORT_ROWS = 50_000
#: Implicit destinations: not connections, always public.
IMPLICIT_DESTINATIONS = (
    {"key": "duckduckgo", "label": "DuckDuckGo (web search fallback)", "kind": "web_search"},
    {"key": "web_fetch", "label": "Web pages read by Web Fetch", "kind": "web_fetch"},
)


def _now() -> datetime.datetime:
    return datetime.datetime.utcnow()


async def _audit(db: AsyncSession, request: Request, admin: User, action: str, resource_id: str, detail: dict) -> None:
    await log_security_event(
        db,
        actor=admin,
        actor_ip=resolve_client_ip(request),
        action=action,
        resource_type="guardrails",
        resource_id=resource_id,
        detail=detail,
    )


# --- meta -----------------------------------------------------------------------------------------------------


async def _route_models(db: AsyncSession) -> list[dict[str, Any]]:
    rows = (
        await db.execute(
            select(AIModel, Connection)
            .join(Connection, Connection.id == AIModel.connection_id)
            .where(Connection.kind == CONNECTION_KIND_MODELS, AIModel.is_enabled.is_(True))
            .order_by(AIModel.display_name, AIModel.id)
        )
    ).all()
    return [
        {
            "id": int(model.id),
            "label": f"{model.display_name or model.external_id} · {conn.name}",
            "trust_level": str(conn.trust_level or "public"),
        }
        for model, conn in rows
    ]


def _library_json(spec: PatternSpec) -> dict[str, Any]:
    return {
        "ref": spec.ref,
        "name": spec.name,
        "description": spec.description,
        "kind": spec.kind,
        "expression": spec.expression,
        "validator": spec.validator,
        "redact_label": spec.redact_label,
        "case_sensitive": spec.case_sensitive,
        "normalize": spec.normalize,
        "must_match": list(spec.must_match),
        "must_not_match": list(spec.must_not_match),
    }


@router.get("/meta")
async def meta(db: AsyncSession = Depends(get_db), _: User = Depends(require_guardrails)):
    return {
        "channels": [{"key": c, "label": CHANNEL_LABELS[c]} for c in CHANNELS],
        "routable_channels": sorted(ROUTABLE_CHANNELS),
        "redactable_channels": sorted(REDACTABLE_CHANNELS),
        "trust_levels": [{"key": t, "label": TRUST_LABELS[t]} for t in TRUST_LEVELS],
        "actions": list(ACTIONS),
        "modes": list(MODES),
        "validators": [{"key": k, "label": v} for k, v in VALIDATOR_LABELS.items()],
        "pattern_kinds": list(PATTERN_KINDS),
        "default_messages": DEFAULT_MESSAGES,
        "library": [_library_json(spec) for spec in LIBRARY],
        "route_models": await _route_models(db),
    }


# --- patterns -------------------------------------------------------------------------------------------------


class PatternIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    description: str | None = Field(None, max_length=500)
    kind: Literal["regex", "words", "domains"] = "regex"
    expression: str | None = None
    entries: list[str] = Field(default_factory=list)
    case_sensitive: bool = False
    normalize: bool = True
    context_words: list[str] = Field(default_factory=list)
    context_window: int = 50
    validator: str | None = None
    never_match: list[str] = Field(default_factory=list)
    redact_label: str = "REDACTED"
    must_match: list[str] = Field(default_factory=list)
    must_not_match: list[str] = Field(default_factory=list)

    def spec(self, ref: str = "draft") -> PatternSpec:
        clean = lambda values: tuple(v.strip() for v in values if v and v.strip())  # noqa: E731
        return PatternSpec(
            ref=ref,
            name=self.name.strip(),
            kind=self.kind,
            expression=(self.expression or "").strip() if self.kind == "regex" else "",
            entries=clean(self.entries) if self.kind != "regex" else (),
            case_sensitive=self.case_sensitive,
            normalize=self.normalize,
            context_words=clean(self.context_words),
            context_window=self.context_window,
            validator=self.validator or None,
            never_match=clean(self.never_match),
            redact_label=(self.redact_label or "").strip().upper(),
            description=(self.description or "").strip(),
            must_match=tuple(v for v in self.must_match if v.strip()),
            must_not_match=tuple(v for v in self.must_not_match if v.strip()),
        )


def _checked(spec: PatternSpec) -> None:
    """Refuse a pattern that cannot be used, or that gets its own samples wrong."""
    try:
        compiled = compile_pattern(spec)
    except PatternError as exc:
        raise HTTPException(400, detail=str(exc)) from None
    problems = check_samples(compiled)
    if problems:
        raise HTTPException(400, detail="The pattern gets its samples wrong. " + " ".join(problems))


def _pattern_values(spec: PatternSpec) -> dict[str, Any]:
    dumps = lambda values: json.dumps(list(values), ensure_ascii=False)  # noqa: E731
    return {
        "name": spec.name,
        "description": spec.description or None,
        "kind": spec.kind,
        "expression": spec.expression or None,
        "entries_json": dumps(spec.entries),
        "case_sensitive": spec.case_sensitive,
        "normalize": spec.normalize,
        "context_words_json": dumps(spec.context_words),
        "context_window": spec.context_window,
        "validator": spec.validator,
        "never_match_json": dumps(spec.never_match),
        "redact_label": spec.redact_label,
        "must_match_json": dumps(spec.must_match),
        "must_not_match_json": dumps(spec.must_not_match),
    }


def _pattern_json(row: GuardrailPattern) -> dict[str, Any]:
    spec = spec_from_row(row)
    return {
        "id": int(row.id),
        "ref": spec.ref,
        "name": spec.name,
        "description": spec.description,
        "kind": spec.kind,
        "expression": spec.expression,
        "entries": list(spec.entries),
        "case_sensitive": spec.case_sensitive,
        "normalize": spec.normalize,
        "context_words": list(spec.context_words),
        "context_window": spec.context_window,
        "validator": spec.validator,
        "never_match": list(spec.never_match),
        "redact_label": spec.redact_label,
        "must_match": list(spec.must_match),
        "must_not_match": list(spec.must_not_match),
        "version": int(row.version or 1),
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


async def _rules(db: AsyncSession) -> list[GuardrailRule]:
    return list(
        (await db.execute(select(GuardrailRule).order_by(GuardrailRule.position, GuardrailRule.id))).scalars().all()
    )


def _hits_since() -> datetime.datetime:
    return _now() - datetime.timedelta(days=7)


async def _pattern_hits(db: AsyncSession) -> dict[str, int]:
    """Finds per pattern ref over the last 7 days, from the events' findings."""
    out: dict[str, int] = {}
    # Events with the same findings are counted together by the database: far fewer rows than events.
    rows = await db.execute(
        select(GuardrailEvent.findings_json, func.count())
        .where(GuardrailEvent.created_at >= _hits_since())
        .group_by(GuardrailEvent.findings_json)
    )
    for value, times in rows.all():
        for finding in json_list(value):
            if isinstance(finding, dict) and finding.get("ref"):
                ref = str(finding["ref"])
                out[ref] = out.get(ref, 0) + int(finding.get("count") or 0) * int(times)
    return out


@router.get("/patterns")
async def list_patterns(db: AsyncSession = Depends(get_db), _: User = Depends(require_guardrails)):
    rules = await _rules(db)
    used: dict[str, list[str]] = {}
    for rule in rules:
        for ref in json_list(rule.patterns_json):
            used.setdefault(str(ref), []).append(str(rule.name))
    hits = await _pattern_hits(db)
    custom = (await db.execute(select(GuardrailPattern).order_by(GuardrailPattern.name))).scalars().all()
    return {
        "custom": [
            {
                **_pattern_json(row),
                "used_by": used.get(f"custom:{row.id}", []),
                "hits_7d": hits.get(f"custom:{row.id}", 0),
            }
            for row in custom
        ],
        "library": [
            {**_library_json(spec), "used_by": used.get(spec.ref, []), "hits_7d": hits.get(spec.ref, 0)}
            for spec in LIBRARY
        ],
    }


@router.post("/patterns")
async def create_pattern(
    body: PatternIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_guardrails_write),
):
    spec = body.spec()
    _checked(spec)
    row = GuardrailPattern(**_pattern_values(spec), version=1, updated_by_user_id=admin.id)
    db.add(row)
    await db.flush()
    await bump_policy_version(db)
    await _audit(db, request, admin, "guardrail_pattern_created", str(row.id), {"after": _pattern_json(row)})
    await db.commit()
    await db.refresh(row)
    return _pattern_json(row)


async def _pattern_or_404(db: AsyncSession, pattern_id: int) -> GuardrailPattern:
    row = await db.get(GuardrailPattern, pattern_id)
    if row is None:
        raise HTTPException(404, detail="No such pattern.")
    return row


@router.put("/patterns/{pattern_id}")
async def update_pattern(
    pattern_id: int,
    body: PatternIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_guardrails_write),
):
    row = await _pattern_or_404(db, pattern_id)
    before = _pattern_json(row)
    spec = body.spec(f"custom:{pattern_id}")
    _checked(spec)
    for key, value in _pattern_values(spec).items():
        setattr(row, key, value)
    row.version = int(row.version or 1) + 1  # type: ignore[assignment]
    row.updated_by_user_id = admin.id
    await db.flush()
    await bump_policy_version(db)
    await _audit(
        db, request, admin, "guardrail_pattern_updated", str(row.id), {"before": before, "after": _pattern_json(row)}
    )
    await db.commit()
    await db.refresh(row)
    return _pattern_json(row)


@router.delete("/patterns/{pattern_id}")
async def delete_pattern(
    pattern_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_guardrails_write),
):
    row = await _pattern_or_404(db, pattern_id)
    users = [str(r.name) for r in await _rules(db) if f"custom:{pattern_id}" in json_list(r.patterns_json)]
    if users:
        raise HTTPException(
            409, detail=f"The pattern is used by: {', '.join(users)}. Take it out of those rules first."
        )
    before = _pattern_json(row)
    await db.delete(row)
    await bump_policy_version(db)
    await _audit(db, request, admin, "guardrail_pattern_deleted", str(pattern_id), {"before": before})
    await db.commit()
    return {"ok": True}


class PatternTestIn(BaseModel):
    pattern: PatternIn
    text: str = Field("", max_length=MAX_TEST_TEXT)


@router.post("/patterns/test")
async def test_pattern(body: PatternTestIn, admin: User = Depends(require_guardrails_write)):
    """What a draft finds in a text, and the samples it gets wrong; a pattern that cannot be used says why."""
    await check_rate_limit(f"admin_guardrail_test:{admin.id}", limit=TESTS_PER_MINUTE, window_seconds=60)
    try:
        compiled = compile_pattern(body.pattern.spec())
    except PatternError as exc:
        return {"ok": False, "error": str(exc), "matches": [], "problems": []}
    matches = compiled.find(body.text)
    return {
        "ok": True,
        "error": None,
        "matches": [{"start": m.start, "end": m.end, "value": m.value} for m in matches],
        "problems": check_samples(compiled),
    }


@router.get("/patterns/export")
async def export_patterns(db: AsyncSession = Depends(get_db), _: User = Depends(require_guardrails)):
    rows = (await db.execute(select(GuardrailPattern).order_by(GuardrailPattern.id))).scalars().all()
    keep = ("name", "description", "kind", "expression", "entries", "case_sensitive", "normalize", "context_words",
            "context_window", "validator", "never_match", "redact_label", "must_match", "must_not_match")  # fmt: skip
    return {
        "format": "alpharouter-guardrail-patterns/1",
        "patterns": [{k: _pattern_json(r)[k] for k in keep} for r in rows],
    }


class PatternImportIn(BaseModel):
    patterns: list[PatternIn] = Field(..., max_length=500)


@router.post("/patterns/import")
async def import_patterns(
    body: PatternImportIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_guardrails_write),
):
    """Add each pattern as a new one; nothing is saved when any of them cannot be used."""
    specs = []
    for index, item in enumerate(body.patterns, start=1):
        spec = item.spec()
        try:
            _checked(spec)
        except HTTPException as exc:
            raise HTTPException(400, detail=f"Pattern {index} ({spec.name}): {exc.detail}") from None
        specs.append(spec)
    for spec in specs:
        db.add(GuardrailPattern(**_pattern_values(spec), version=1, updated_by_user_id=admin.id))
    await bump_policy_version(db)
    await _audit(db, request, admin, "guardrail_patterns_imported", "patterns", {"names": [s.name for s in specs]})
    await db.commit()
    return {"imported": len(specs)}


# --- rules ----------------------------------------------------------------------------------------------------


class RuleIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    description: str | None = Field(None, max_length=500)
    mode: Literal["off", "monitor", "enforce"] = "off"
    patterns: list[str] = Field(..., min_length=1, max_length=50)
    match_mode: Literal["any", "all"] = "any"
    min_matches: int = Field(1, ge=1, le=1000)
    channels: list[str] = Field(..., min_length=1)
    destinations: list[str] = Field(default_factory=list)
    action: Literal["block", "redact", "route"] = "block"
    route_model_id: int | None = None
    user_message: str | None = Field(None, max_length=500)


async def _validated_rule(db: AsyncSession, body: RuleIn) -> dict[str, Any]:
    channels = list(dict.fromkeys(c for c in body.channels))
    if not set(channels) <= set(CHANNELS):
        raise HTTPException(400, detail=f"Channels are some of: {', '.join(CHANNELS)}.")
    destinations = list(dict.fromkeys(body.destinations))
    if not set(destinations) <= set(TRUST_LEVELS):
        raise HTTPException(400, detail=f"Destinations are trust levels: {', '.join(TRUST_LEVELS)}.")
    refs = list(dict.fromkeys(str(r) for r in body.patterns))
    custom_ids = [int(r.split(":", 1)[1]) for r in refs if r.startswith("custom:") and r.split(":", 1)[1].isdigit()]
    existing = {
        int(i)
        for i in (await db.execute(select(GuardrailPattern.id).where(GuardrailPattern.id.in_(custom_ids)))).scalars()
    }
    for ref in refs:
        known = (
            library_pattern(ref) is not None
            if ref.startswith("lib:")
            else (
                ref.startswith("custom:") and ref.split(":", 1)[1].isdigit() and int(ref.split(":", 1)[1]) in existing
            )
        )
        if not known:
            raise HTTPException(400, detail=f"Unknown pattern: {ref}.")
    route_model_id = None
    if body.action == "route":
        if not set(channels) <= ROUTABLE_CHANNELS:
            raise HTTPException(
                400, detail="Only chat, attached files, the extension and the Gateway can be routed to another model."
            )
        if body.route_model_id is None:
            raise HTTPException(400, detail="Choose the model to route to.")
        model = await db.get(AIModel, body.route_model_id)
        conn = await db.get(Connection, model.connection_id) if model is not None else None
        if model is None or not model.is_enabled or conn is None or conn.kind != CONNECTION_KIND_MODELS:
            raise HTTPException(400, detail="The model to route to must be an enabled chat model.")
        route_model_id = int(model.id)
    if body.action == "redact" and not set(channels) <= REDACTABLE_CHANNELS:
        raise HTTPException(400, detail="An address read by Web Fetch cannot be masked: block it instead.")
    return {
        "name": body.name.strip(),
        "description": (body.description or "").strip() or None,
        "mode": body.mode,
        "patterns_json": json.dumps(refs),
        "match_mode": body.match_mode,
        "min_matches": body.min_matches,
        "channels_json": json.dumps(channels),
        "destinations_json": json.dumps(destinations),
        "action": body.action,
        "route_model_id": route_model_id,
        "user_message": (body.user_message or "").strip() or None,
    }


async def _assignment_counts(db: AsyncSession) -> dict[int, dict[str, int]]:
    out: dict[int, dict[str, int]] = {}
    for rule_id, effect, count in (
        await db.execute(
            select(GuardrailRuleAssignment.rule_id, GuardrailRuleAssignment.effect, func.count()).group_by(
                GuardrailRuleAssignment.rule_id, GuardrailRuleAssignment.effect
            )
        )
    ).all():
        out.setdefault(int(rule_id), {})[str(effect)] = int(count)
    return out


async def _rule_hits(db: AsyncSession) -> dict[int, int]:
    rows = (
        await db.execute(
            select(GuardrailEvent.rule_id, func.count())
            .where(GuardrailEvent.created_at >= _hits_since(), GuardrailEvent.rule_id.is_not(None))
            .group_by(GuardrailEvent.rule_id)
        )
    ).all()
    return {int(rule_id): int(count) for rule_id, count in rows}


def _rule_json(
    row: GuardrailRule,
    *,
    names: dict[str, str],
    models: dict[int, str],
    counts: dict[str, int] | None = None,
    hits: int = 0,
) -> dict[str, Any]:
    refs = [str(r) for r in json_list(row.patterns_json)]
    return {
        "id": int(row.id),
        "name": str(row.name),
        "description": row.description,
        "mode": str(row.mode),
        "position": int(row.position or 0),
        "patterns": refs,
        "pattern_names": [names.get(r, f"{r} (missing)") for r in refs],
        "missing_patterns": [r for r in refs if r not in names],
        "match_mode": str(row.match_mode),
        "min_matches": int(row.min_matches or 1),
        "channels": json_list(row.channels_json),
        "destinations": json_list(row.destinations_json),
        "action": str(row.action),
        "route_model_id": row.route_model_id,
        "route_model_label": models.get(int(row.route_model_id)) if row.route_model_id is not None else None,
        "user_message": row.user_message,
        "access_type": str(row.access_type),
        "allow_count": (counts or {}).get("allow", 0),
        "deny_count": (counts or {}).get("deny", 0),
        "version": int(row.version or 1),
        "hits_7d": hits,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "updated_by_user_id": row.updated_by_user_id,
    }


async def _naming(db: AsyncSession) -> tuple[dict[str, str], dict[int, str]]:
    names = {spec.ref: spec.name for spec in LIBRARY}
    for pid, pname in (await db.execute(select(GuardrailPattern.id, GuardrailPattern.name))).all():
        names[f"custom:{pid}"] = str(pname)
    models = {m["id"]: m["label"] for m in await _route_models(db)}
    return names, models


@router.get("/rules")
async def list_rules(db: AsyncSession = Depends(get_db), _: User = Depends(require_guardrails)):
    names, models = await _naming(db)
    counts = await _assignment_counts(db)
    hits = await _rule_hits(db)
    return [
        _rule_json(row, names=names, models=models, counts=counts.get(int(row.id)), hits=hits.get(int(row.id), 0))
        for row in await _rules(db)
    ]


async def _rule_or_404(db: AsyncSession, rule_id: int) -> GuardrailRule:
    row = await db.get(GuardrailRule, rule_id)
    if row is None:
        raise HTTPException(404, detail="No such rule.")
    return row


async def _one_rule_json(db: AsyncSession, row: GuardrailRule) -> dict[str, Any]:
    names, models = await _naming(db)
    counts = (await _assignment_counts(db)).get(int(row.id))
    return _rule_json(row, names=names, models=models, counts=counts, hits=(await _rule_hits(db)).get(int(row.id), 0))


@router.post("/rules")
async def create_rule(
    body: RuleIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_guardrails_write),
):
    values = await _validated_rule(db, body)
    last = (await db.execute(select(func.max(GuardrailRule.position)))).scalar()
    row = GuardrailRule(
        **values,
        position=int(last or 0) + 1,
        access_type="public",
        acl_version=0,
        version=1,
        updated_by_user_id=admin.id,
    )
    db.add(row)
    await db.flush()
    await bump_policy_version(db)
    saved = await _one_rule_json(db, row)
    await _audit(db, request, admin, "guardrail_rule_created", str(row.id), {"after": saved})
    await db.commit()
    return saved


@router.put("/rules/{rule_id}")
async def update_rule(
    rule_id: int,
    body: RuleIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_guardrails_write),
):
    row = await _rule_or_404(db, rule_id)
    before = await _one_rule_json(db, row)
    for key, value in (await _validated_rule(db, body)).items():
        setattr(row, key, value)
    row.version = int(row.version or 1) + 1  # type: ignore[assignment]
    row.updated_by_user_id = admin.id
    await db.flush()
    await bump_policy_version(db)
    after = await _one_rule_json(db, row)
    await _audit(db, request, admin, "guardrail_rule_updated", str(row.id), {"before": before, "after": after})
    await db.commit()
    return after


class RuleModeIn(BaseModel):
    mode: Literal["off", "monitor", "enforce"]


@router.patch("/rules/{rule_id}/mode")
async def set_rule_mode(
    rule_id: int,
    body: RuleModeIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_guardrails_write),
):
    row = await _rule_or_404(db, rule_id)
    before = str(row.mode)
    row.mode = body.mode  # type: ignore[assignment]
    row.version = int(row.version or 1) + 1  # type: ignore[assignment]
    row.updated_by_user_id = admin.id
    await bump_policy_version(db)
    await _audit(
        db,
        request,
        admin,
        "guardrail_rule_mode_changed",
        str(row.id),
        {"rule": str(row.name), "before": before, "after": body.mode},
    )
    await db.commit()
    return await _one_rule_json(db, row)


class RuleMoveIn(BaseModel):
    direction: Literal["up", "down"]


@router.post("/rules/{rule_id}/move")
async def move_rule(
    rule_id: int,
    body: RuleMoveIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_guardrails_write),
):
    rules = await _rules(db)
    index = next((i for i, r in enumerate(rules) if int(r.id) == rule_id), None)
    if index is None:
        raise HTTPException(404, detail="No such rule.")
    other = index - 1 if body.direction == "up" else index + 1
    if 0 <= other < len(rules):
        rules[index], rules[other] = rules[other], rules[index]
    for position, rule in enumerate(rules, start=1):
        rule.position = position  # type: ignore[assignment]
    await bump_policy_version(db)
    await _audit(db, request, admin, "guardrail_rules_reordered", str(rule_id), {"order": [str(r.name) for r in rules]})
    await db.commit()
    return await list_rules(db)


@router.delete("/rules/{rule_id}")
async def delete_rule(
    rule_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_guardrails_write),
):
    row = await _rule_or_404(db, rule_id)
    before = await _one_rule_json(db, row)
    await db.execute(delete(GuardrailRuleAssignment).where(GuardrailRuleAssignment.rule_id == rule_id))
    await db.delete(row)
    await bump_policy_version(db)
    await _audit(db, request, admin, "guardrail_rule_deleted", str(rule_id), {"before": before})
    await db.commit()
    return {"ok": True}


# --- who a rule applies to -----------------------------------------------------------------------------------


async def _access_json(db: AsyncSession, row: GuardrailRule) -> dict[str, Any]:
    grants: list[dict[str, Any]] = []
    for a in (
        await db.execute(select(GuardrailRuleAssignment).where(GuardrailRuleAssignment.rule_id == row.id))
    ).scalars():
        if a.user_id is not None:
            grants.append({"target_type": "user", "target": int(a.user_id), "effect": a.effect})
        elif a.group_id is not None:
            grants.append({"target_type": "group", "target": int(a.group_id), "effect": a.effect})
        elif a.department:
            grants.append({"target_type": "department", "target": a.department, "effect": a.effect})
        elif a.role_slug:
            grants.append({"target_type": "role", "target": a.role_slug, "effect": a.effect})
    return {
        "access_type": str(row.access_type),
        "acl_version": int(row.acl_version or 0),
        "grants": grants,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


@router.get("/rules/{rule_id}/access")
async def get_rule_access(rule_id: int, db: AsyncSession = Depends(get_db), _: User = Depends(require_guardrails)):
    return await _access_json(db, await _rule_or_404(db, rule_id))


class GrantIn(BaseModel):
    target_type: Literal["user", "group", "department", "role"]
    target: int | str
    effect: Literal["allow", "deny"] = "allow"


class AccessIn(BaseModel):
    access_type: str
    grants: list[GrantIn] = Field(default_factory=list, max_length=500)
    acl_version: int | None = None


@router.put("/rules/{rule_id}/access")
async def put_rule_access(
    rule_id: int,
    body: AccessIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_guardrails_write),
):
    row = await _rule_or_404(db, rule_id)
    access = (body.access_type or "").strip().lower()
    if access not in VALID_ACCESS_TYPES:
        raise HTTPException(400, detail="access_type must be 'public' or 'private'.")
    if body.acl_version is not None and body.acl_version != int(row.acl_version or 0):
        raise HTTPException(409, detail="Someone else changed who this rule applies to; reload and try again.")
    try:
        rows = await validated_grants(db, [AccessGrant(g.target_type, g.target, g.effect) for g in body.grants])
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc)) from None
    before = await _access_json(db, row)
    await db.execute(delete(GuardrailRuleAssignment).where(GuardrailRuleAssignment.rule_id == rule_id))
    for values in rows:
        db.add(GuardrailRuleAssignment(rule_id=rule_id, assigned_by_user_id=admin.id, assigned_at=_now(), **values))
    row.access_type = access  # type: ignore[assignment]
    row.acl_version = int(row.acl_version or 0) + 1  # type: ignore[assignment]
    row.version = int(row.version or 1) + 1  # type: ignore[assignment]
    row.updated_by_user_id = admin.id
    await db.flush()
    await bump_policy_version(db)
    after = await _access_json(db, row)
    await _audit(
        db,
        request,
        admin,
        "guardrail_rule_access_changed",
        str(rule_id),
        {"rule": str(row.name), "before": before, "after": after},
    )
    await db.commit()
    return after


# --- destinations ---------------------------------------------------------------------------------------------


@router.get("/destinations")
async def list_destinations(db: AsyncSession = Depends(get_db), _: User = Depends(require_guardrails)):
    rows = (await db.execute(select(Connection).order_by(Connection.kind, Connection.name))).scalars().all()
    return {
        "connections": [
            {
                "id": int(c.id),
                "name": str(c.name),
                "kind": str(c.kind),
                "provider_type": str(c.provider_type),
                "is_active": bool(c.is_active),
                "trust_level": str(c.trust_level or "public"),
            }
            for c in rows
            if c.kind in (CONNECTION_KIND_MODELS, CONNECTION_KIND_WEB_SEARCH)
        ],
        "implicit": [{**d, "trust_level": "public"} for d in IMPLICIT_DESTINATIONS],
    }


class TrustIn(BaseModel):
    trust_level: Literal["internal", "trusted", "public"]


@router.put("/destinations/{connection_id}")
async def set_destination_trust(
    connection_id: int,
    body: TrustIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_guardrails_write),
):
    conn = await db.get(Connection, connection_id)
    if conn is None:
        raise HTTPException(404, detail="No such connection.")
    before = str(conn.trust_level or "public")
    conn.trust_level = body.trust_level  # type: ignore[assignment]
    await bump_policy_version(db)
    await _audit(
        db,
        request,
        admin,
        "guardrail_destination_trust_changed",
        str(connection_id),
        {"connection": str(conn.name), "before": before, "after": body.trust_level},
    )
    await db.commit()
    return {"id": connection_id, "trust_level": body.trust_level}


# --- settings -------------------------------------------------------------------------------------------------


class SettingsIn(BaseModel):
    fail_closed: bool = True
    restore_replies: bool = True
    event_retention_days: int = Field(180, ge=7, le=3650)
    alert_emails: list[str] = Field(default_factory=list, max_length=20)


@router.get("/settings")
async def get_settings(db: AsyncSession = Depends(get_db), _: User = Depends(require_guardrails)):
    return (await load_settings(db)).as_dict()


@router.put("/settings")
async def put_settings(
    body: SettingsIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_guardrails_write),
):
    emails = []
    for email in body.alert_emails:
        email = email.strip()
        if not email:
            continue
        if "@" not in email or len(email) > 254 or any(c.isspace() for c in email):
            raise HTTPException(400, detail=f"Not an email address: {email}")
        emails.append(email)
    before = (await load_settings(db)).as_dict()
    after = GuardrailSettings(
        fail_closed=body.fail_closed,
        restore_replies=body.restore_replies,
        event_retention_days=body.event_retention_days,
        alert_emails=emails,
    )
    await save_settings(db, after)
    await _audit(
        db, request, admin, "guardrail_settings_updated", "settings", {"before": before, "after": after.as_dict()}
    )
    await db.commit()
    return after.as_dict()


# --- Test a text ----------------------------------------------------------------------------------------------


class TextTestIn(BaseModel):
    text: str = Field(..., max_length=MAX_TEST_TEXT)
    channel: str = "chat"
    trust_level: Literal["internal", "trusted", "public"] = "public"
    #: Whose request to imagine; none: a person no rule names (only rules for everyone apply).
    user_id: int | None = None


def _test_subject_for_everyone() -> ResourceAccessSubject:
    return ResourceAccessSubject(user_id=None, public_only=True)


@router.post("/test")
async def test_text(
    body: TextTestIn, db: AsyncSession = Depends(get_db), admin: User = Depends(require_guardrails_write)
):
    """What the rules would do to a text: each rule that matches, and the result. Nothing is recorded."""
    await check_rate_limit(f"admin_guardrail_test:{admin.id}", limit=TESTS_PER_MINUTE, window_seconds=60)
    if body.channel not in CHANNELS:
        raise HTTPException(400, detail=f"Channel is one of: {', '.join(CHANNELS)}.")
    from app.services.guardrail_policy import Segment, message_segments

    policy: Policy = await load_policy(db)
    subject = (
        await resolve_resource_access_subject(db, user_id=body.user_id)
        if body.user_id is not None
        else _test_subject_for_everyone()
    )
    if body.channel == "chat":
        segments = message_segments([{"role": "user", "content": body.text}], channel="chat")
    else:
        segments = [Segment(body.channel, body.text, message=0, part=None, offset=0)]
    # Monitored rules are tried as if enforcing, so the administrator sees what they would do. Copies: the
    # cached policy is shared by every request of this worker.
    from dataclasses import replace

    modes = {r.id: r.mode for r in policy.rules}
    trial = Policy(version="test", rules=[replace(r, mode="enforce") for r in policy.rules if r.mode != "off"])
    verdict = decide(trial, segments, destination=Destination(label="test", trust=body.trust_level), subject=subject)
    notices = verdict.notices("the routed model")
    preview = mask_text(body.text, [(s, m, label) for s, m, label in _absolute(verdict.to_mask)], Masker())
    return {
        "action": verdict.action,
        "message": notices[0] if notices else None,
        "masked": preview if verdict.to_mask else None,
        "rules": [
            {
                "id": hit.rule.id,
                "name": hit.rule.name,
                "mode": modes.get(hit.rule.id, hit.rule.mode),
                "action": hit.rule.action,
                "applied": verdict.applied(hit),
                "count": hit.count,
                "matches": [
                    {"start": s.offset + m.start, "end": s.offset + m.end, "value": m.value, "pattern": m.ref}
                    for s, m in hit.matches
                ],
            }
            for hit in verdict.enforced
        ],
    }


def _absolute(to_mask: list) -> list:
    """Finds with their offsets in the whole text (a chat text is split into typed words and attachments)."""
    from dataclasses import replace

    out = []
    for segment, match, label in to_mask:
        out.append((segment, replace(match, start=segment.offset + match.start, end=segment.offset + match.end), label))
    return out


# --- what the rules did -------------------------------------------------------------------------------------


def _event_json(row: GuardrailEvent) -> dict[str, Any]:
    return {
        "id": int(row.id),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "rule_id": row.rule_id,
        "rule_name": row.rule_name,
        "rule_version": row.rule_version,
        "action": row.action,
        "intended_action": row.intended_action,
        "channel": row.channel,
        "destination": row.destination,
        "destination_trust": row.destination_trust,
        "user_id": row.user_id,
        "username": row.username,
        "alpha_router_api_key_id": row.alpha_router_api_key_id,
        "source": row.source,
        "model_ref": row.model_ref,
        "match_count": int(row.match_count or 0),
        "findings": json_list(row.findings_json),
        "message": row.message,
    }


def _event_filters(
    days: int, action: str | None, rule_id: int | None, channel: str | None, username: str | None
) -> list[Any]:
    filters: list[Any] = [GuardrailEvent.created_at >= _now() - datetime.timedelta(days=days)]
    if action:
        filters.append(GuardrailEvent.action == action)
    if rule_id is not None:
        filters.append(GuardrailEvent.rule_id == rule_id)
    if channel:
        filters.append(GuardrailEvent.channel == channel)
    if username:
        filters.append(func.lower(GuardrailEvent.username).like(f"{username.strip().lower()}%"))
    return filters


@router.get("/events")
async def list_events(
    days: int = Query(7, ge=1, le=3650),
    action: str | None = None,
    rule_id: int | None = None,
    channel: str | None = None,
    username: str | None = Query(None, max_length=100),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_guardrails),
):
    filters = _event_filters(days, action, rule_id, channel, username)
    total = (await db.execute(select(func.count()).select_from(GuardrailEvent).where(*filters))).scalar() or 0
    rows = (
        await db.execute(
            select(GuardrailEvent).where(*filters).order_by(GuardrailEvent.id.desc()).limit(limit).offset(offset)
        )
    ).scalars()
    return {"total": int(total), "items": [_event_json(r) for r in rows]}


def _csv_cell(value: Any) -> str:
    text = "" if value is None else str(value)
    # A cell a spreadsheet would run as a formula is written as text.
    return "'" + text if text[:1] in ("=", "+", "-", "@") else text


@router.get("/events/export.csv")
async def export_events(
    request: Request,
    days: int = Query(30, ge=1, le=3650),
    action: str | None = None,
    rule_id: int | None = None,
    channel: str | None = None,
    username: str | None = Query(None, max_length=100),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_guardrails),
):
    filters = _event_filters(days, action, rule_id, channel, username)
    rows = (
        (await db.execute(select(GuardrailEvent).where(*filters).order_by(GuardrailEvent.id.desc()).limit(EXPORT_ROWS)))
        .scalars()
        .all()
    )
    await _audit(
        db,
        request,
        admin,
        "guardrail_events_exported",
        "events",
        {"days": days, "action": action, "rule_id": rule_id, "channel": channel, "rows": len(rows)},
    )
    await db.commit()
    buffer = io.StringIO()
    buffer.write("﻿")
    writer = csv.writer(buffer)
    writer.writerow(
        ["time", "user", "rule", "action", "would have", "channel", "destination", "trust", "finds", "found"]
    )
    for row in rows:
        found = "; ".join(
            f"{f.get('name')} ×{f.get('count')}" for f in json_list(row.findings_json) if isinstance(f, dict)
        )
        writer.writerow(
            [
                _csv_cell(v)
                for v in (
                    row.created_at.isoformat() if row.created_at else "",
                    row.username or "",
                    row.rule_name or "",
                    row.action,
                    row.intended_action or "",
                    row.channel,
                    row.destination or "",
                    row.destination_trust or "",
                    row.match_count,
                    found,
                )
            ]  # fmt: skip
        )
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="guardrail-events.csv"'},
    )


@router.get("/overview")
async def overview(db: AsyncSession = Depends(get_db), _: User = Depends(require_guardrails)):
    since7 = _now() - datetime.timedelta(days=7)
    since30 = (_now() - datetime.timedelta(days=29)).replace(hour=0, minute=0, second=0, microsecond=0)
    rules = await _rules(db)
    modes = {m: sum(1 for r in rules if r.mode == m) for m in MODES}
    totals = {a: 0 for a in ("block", "redact", "route", "monitor", "engine_error")}
    per_action_rule: dict[str, dict[str, int]] = {}
    for action, rule_name, count in (
        await db.execute(
            select(GuardrailEvent.action, GuardrailEvent.rule_name, func.count())
            .where(GuardrailEvent.created_at >= since7)
            .group_by(GuardrailEvent.action, GuardrailEvent.rule_name)
        )
    ).all():
        totals[str(action)] = totals.get(str(action), 0) + int(count)
        if rule_name:
            per_action_rule.setdefault(str(action), {})[str(rule_name)] = int(count)
    channels = [
        {"channel": str(c), "count": int(n)}
        for c, n in (
            await db.execute(
                select(GuardrailEvent.channel, func.count())
                .where(GuardrailEvent.created_at >= since7, GuardrailEvent.action != "engine_error")
                .group_by(GuardrailEvent.channel)
                .order_by(func.count().desc())
            )
        ).all()
    ]
    top_rules = [
        {"rule_id": rid, "name": str(name), "count": int(n)}
        for rid, name, n in (
            await db.execute(
                select(GuardrailEvent.rule_id, GuardrailEvent.rule_name, func.count())
                .where(GuardrailEvent.created_at >= since7, GuardrailEvent.rule_id.is_not(None))
                .group_by(GuardrailEvent.rule_id, GuardrailEvent.rule_name)
                .order_by(func.count().desc())
                .limit(5)
            )
        ).all()
    ]
    days: dict[str, dict[str, int]] = {}
    for i in range(30):
        day = (since30 + datetime.timedelta(days=i)).date().isoformat()
        days[day] = {"block": 0, "redact": 0, "route": 0, "monitor": 0}
    day_of = func.date(GuardrailEvent.created_at)
    for day_value, action, count in (
        await db.execute(
            select(day_of, GuardrailEvent.action, func.count())
            .where(GuardrailEvent.created_at >= since30)
            .group_by(day_of, GuardrailEvent.action)
        )
    ).all():
        day = day_value.isoformat() if hasattr(day_value, "isoformat") else str(day_value)[:10]
        if day in days and action in days[day]:
            days[day][str(action)] += int(count)
    return {
        "rules": modes,
        "totals_7d": totals,
        "top_by_action": {
            action: [{"name": n, "count": c} for n, c in sorted(by_rule.items(), key=lambda item: -item[1])[:2]]
            for action, by_rule in per_action_rule.items()
        },
        "by_channel": channels,
        "top_rules": top_rules,
        "daily": [{"date": d, **v} for d, v in days.items()],
    }
