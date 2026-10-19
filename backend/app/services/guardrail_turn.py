"""Guardrails on a chat turn: the web chat, the browser extension and the Gateway.

Two checks, because a turn's text arrives in two steps:

1. Before the model is asked for anything (``guard_request``, in the
   preflight): what the client sent - the person's messages, their attached
   files and the conversation so far. A rule may block the turn (a 422 the
   person reads), mask values in place, or route the turn to the model the
   administrator chose; then the turn is checked again for that model.
2. Just before the request leaves (``guard_context``, in the turn's
   preparation): what the platform added - memory, project files, knowledge,
   the chat's summary - and an Agent's own prompt. A block here ends the turn
   with an error frame (the stream has begun).

What a turn masked, and what the person is told, travel with the request body
under ``GUARDRAIL_BODY_KEY`` - plain data the client can never set (the
Gateway drops server keys; the web chat builds its body itself).
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.connection import Connection
from app.models.user import User
from app.services.guardrail_policy import (
    Destination,
    load_policy,
    EventContext,
    GuardrailEngineError,
    Masker,
    Segment,
    Verdict,
    inspect,
    mask_messages,
    message_segments,
)

#: Server-owned body key: ``{"values": {placeholder: value}, "notices": [str]}``.
GUARDRAIL_BODY_KEY = "_guardrail"
#: Server-owned body key set by the web chat for a turn from the browser extension.
VIA_EXTENSION_BODY_KEY = "_via_extension"
#: Server-owned body key set by the web chat when the turn's model was checked and pinned for shared page
#: content: a rule that would route such a turn elsewhere blocks it instead.
MODEL_PINNED_BODY_KEY = "_model_pinned"
BLOCKED_CODE = "guardrail_blocked"
UNAVAILABLE_CODE = "guardrail_unavailable"


def turn_channel(body: dict[str, Any], source: str | None) -> str:
    if source != "alpha_router_chat":
        return "gateway"
    if body.get(VIA_EXTENSION_BODY_KEY):
        return "extension"
    return "chat"


async def model_destination(db: AsyncSession, ai_model: Any) -> Destination:
    conn = await db.get(Connection, ai_model.connection_id) if getattr(ai_model, "connection_id", None) else None
    model_name = str(ai_model.display_name or ai_model.external_id or ai_model.id)
    return Destination(
        label=f"{conn.name} · {model_name}" if conn is not None else model_name,
        trust=str(conn.trust_level or "public") if conn is not None else "public",
        connection_id=int(conn.id) if conn is not None else None,
        model_id=int(ai_model.id),
        model_ref=f"model::{ai_model.id}",
    )


async def _event_context(
    db: AsyncSession, *, user_id: int | None, alpha_router_api_key_id: int | None, source: str | None
) -> EventContext:
    username = None
    if user_id is not None:
        user = await db.get(User, user_id)
        username = str(user.username) if user is not None and user.username else None
    return EventContext(
        user_id=user_id, username=username, alpha_router_api_key_id=alpha_router_api_key_id, source=source
    )


async def _rules_watch(db: AsyncSession) -> bool:
    """Whether any rule is on: a turn with no rule to apply costs one read of the policy version."""
    try:
        return (await load_policy(db)).active
    except Exception:  # noqa: BLE001 -- a policy that cannot be read is checked (and recorded) by inspect()
        return True


def turn_state(body: dict[str, Any]) -> dict[str, Any]:
    state = body.get(GUARDRAIL_BODY_KEY)
    if not isinstance(state, dict):
        state = {"values": {}, "notices": [], "hidden": []}
        body[GUARDRAIL_BODY_KEY] = state
    state.setdefault("values", {})
    state.setdefault("notices", [])
    #: Placeholders for values the platform added (an Agent's prompt, memory): never given back in a reply.
    state.setdefault("hidden", [])
    return state


def _new_from(messages: list[dict[str, Any]]) -> int:
    """The first message new in this request: the last one the person wrote (the rest was sent before)."""
    for index in range(len(messages) - 1, -1, -1):
        if messages[index].get("role") == "user":
            return index
    return max(len(messages) - 1, 0)


def masker_for(state: dict[str, Any]) -> Masker:
    """A masker that goes on numbering where the turn's earlier masking stopped."""
    masker = Masker()
    for token, value in (state.get("values") or {}).items():
        label, _, number = str(token).strip("[]").rpartition("_")
        masker.values[token] = value
        masker._by_value[(label, value)] = token
        masker._counts[label] = max(masker._counts.get(label, 0), int(number) if number.isdigit() else 0)
    return masker


def _blocked(verdict: Verdict) -> HTTPException:
    message = verdict.notices()[0] if verdict.notices() else "This was not sent."
    return HTTPException(status_code=422, detail={"code": BLOCKED_CODE, "message": message})


def _unavailable(exc: GuardrailEngineError) -> HTTPException:
    return HTTPException(status_code=503, detail={"code": UNAVAILABLE_CODE, "message": str(exc)})


async def guard_request(
    db: AsyncSession,
    body: dict[str, Any],
    *,
    ai_model: Any,
    user_id: int | None,
    alpha_router_api_key_id: int | None,
    source: str | None,
    agent_turn: bool = False,
    routed_from: int | None = None,
) -> int | None:
    """Check what the client sent; mask in place, raise to block, or return the model id to route to."""
    if not await _rules_watch(db):
        return None
    channel = turn_channel(body, source)
    messages = list(body.get("messages") or [])
    segments = message_segments(messages, channel=channel)
    if not segments:
        return None
    destination = await model_destination(db, ai_model)
    ctx = await _event_context(db, user_id=user_id, alpha_router_api_key_id=alpha_router_api_key_id, source=source)
    try:
        verdict = await inspect(
            db,
            segments,
            destination=destination,
            ctx=ctx,
            ignore_route_to=routed_from,
            # An Agent's model is its own, and a model pinned for shared page content stays: a rule that
            # would route such a turn stops it instead.
            route_as_block=agent_turn or routed_from is not None or bool(body.get(MODEL_PINNED_BODY_KEY)),
            new_from=_new_from(messages),
        )
    except GuardrailEngineError as exc:
        raise _unavailable(exc) from exc
    if verdict.blocked:
        raise _blocked(verdict)
    state = turn_state(body)
    if verdict.to_mask:
        masker = masker_for(state)
        body["messages"] = mask_messages(messages, verdict.to_mask, masker)
        state["values"] = dict(masker.values)
    label = str(ai_model.display_name or ai_model.external_id or "")
    pending = state.pop("route_notice", None)
    if pending:
        # Checked again after routing: the notice names the model the turn went to.
        state["notices"].append(str(pending).replace("{model}", label or "another model"))
    for hit in verdict.enforced:
        if not verdict.applied(hit) or hit.action == "route":
            continue
        notice = hit.message.replace("{model}", label or "another model")
        if notice not in state["notices"]:
            state["notices"].append(notice)
    if verdict.action == "route" and verdict.deciding is not None:
        state["route_notice"] = verdict.deciding.message
        return verdict.deciding.rule.route_model_id
    return None


def _client_contents(body: dict[str, Any]) -> set[str]:
    return {json.dumps(m.get("content"), sort_keys=True, ensure_ascii=False) for m in body.get("messages") or []}


async def guard_context(
    db: AsyncSession,
    body: dict[str, Any],
    messages: list[dict[str, Any]],
    *,
    ai_model: Any,
    user_id: int | None,
    alpha_router_api_key_id: int | None,
    source: str | None,
) -> tuple[list[dict[str, Any]], str | None]:
    """Check what the platform added to the turn; the messages to send, or the message to end the turn with."""
    if not await _rules_watch(db):
        return messages, None
    sent = _client_contents(body)
    channel = turn_channel(body, source)
    skip = {
        i for i, m in enumerate(messages) if json.dumps(m.get("content"), sort_keys=True, ensure_ascii=False) in sent
    }
    segments: list[Segment] = []
    for i, message in enumerate(messages):
        if i in skip:
            continue
        own = "context" if message.get("role") == "system" else channel
        # message_segments numbers the messages it is given from 0: each is put back at its place in the turn.
        segments.extend(
            Segment(s.channel, s.text, i, s.part, s.offset) for s in message_segments([message], channel=own)
        )
    if not segments:
        return messages, None
    destination = await model_destination(db, ai_model)
    ctx = await _event_context(db, user_id=user_id, alpha_router_api_key_id=alpha_router_api_key_id, source=source)
    try:
        verdict = await inspect(db, segments, destination=destination, ctx=ctx, route_as_block=True)
    except GuardrailEngineError as exc:
        return messages, str(exc)
    if verdict.blocked:
        notices = verdict.notices()
        return messages, notices[0] if notices else "This was not sent."
    state = turn_state(body)
    if verdict.to_mask:
        masker = masker_for(state)
        before = set(masker.values)
        messages = mask_messages(messages, verdict.to_mask, masker)
        state["values"] = dict(masker.values)
        # A value first seen here was not the person's to see: the model may be asked to repeat it.
        state["hidden"] = sorted(set(state["hidden"]) | (set(masker.values) - before))
    for notice in verdict.notices():
        if notice not in state["notices"]:
            state["notices"].append(notice)
    return messages, None


async def guardrail_reply_state(db: AsyncSession, body: dict[str, Any]) -> tuple[dict[str, str], list[str]]:
    """The values to give back in the reply (when the administrator wants them back) and the notices."""
    state = body.get(GUARDRAIL_BODY_KEY)
    if not isinstance(state, dict):
        return {}, []
    hidden = {str(t) for t in state.get("hidden") or []}
    values = {str(k): str(v) for k, v in (state.get("values") or {}).items() if str(k) not in hidden}
    notices = [str(n) for n in state.get("notices") or []]
    if values:
        from app.services.guardrail_policy import load_settings

        if not (await load_settings(db)).restore_replies:
            values = {}
    return values, notices
