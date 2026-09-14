"""Atomic reservations for user budgets and Alpharouter API-key credit."""

from __future__ import annotations

import datetime
import uuid

import litellm
from fastapi import HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.api_key import AlphaRouterApiKey
from app.models.budget_reservation import BudgetReservation
from app.models.model_catalog import AIModel
from app.models.user import User
from app.services.budget_service import (
    BUDGET_EXCEEDED_DETAIL,
    NO_PLAN_BUDGET_DETAIL,
    ensure_budget_period,
)
from app.services.alpha_router_api_key_service import ensure_key_usable

SUBJECT_USER = "user"
SUBJECT_ALPHA_ROUTER_KEY = "alpha_router_key"
# Sibling of the DDL (56023113), admin-bootstrap (56023114) and scheduler
# leader (56023115) locks.
RECONCILE_LOCK_ID = 56023116
STATUS_HELD = "held"
STATUS_SETTLED = "settled"
STATUS_RELEASED = "released"
STATUS_EXPIRED = "expired"


def _now() -> datetime.datetime:
    return datetime.datetime.utcnow()


def _positive_float(value: float | int | None, fallback: float) -> float:
    try:
        amount = float(value or 0)
    except (TypeError, ValueError):
        amount = 0.0
    return amount if amount > 0 else fallback


def _clamp_hold(amount: float, fallback: float) -> float:
    settings = get_settings()
    maximum = max(0.01, min(100.0, float(settings.budget_max_hold_usd or 5.0)))
    return round(max(0.0001, min(maximum, _positive_float(amount, fallback))), 8)


#: Flat per-image prompt-token estimate for multimodal turns. Providers tokenize
#: an image into roughly 1k-1.6k tokens regardless of file size, so the byte
#: length of a base64 data URL says nothing about the real charge. Deliberately
#: on the high side of that range: the hold is a ceiling, ``settle`` charges the
#: provider's actual usage.
IMAGE_PROMPT_TOKENS = 1600


def _content_prompt_bytes(content: object) -> int:
    """Prompt bytes for one message ``content``, excluding embedded media blobs.

    ``content`` is either a plain string or an OpenAI-style list of parts. For the
    list form the client inlines images as ``{"type": "image_url", "image_url":
    {"url": "data:image/...;base64,<megabytes>"}}``. Stringifying that list (the
    previous behaviour) counted the whole base64 payload as prompt text and
    overestimated a 1 MB image by ~200x, which made the reservation exceed a
    healthy remaining budget and rejected the turn. Only text parts are measured
    here; media parts are priced by ``_content_media_tokens``.
    """
    if isinstance(content, str):
        return len(content.encode("utf-8"))
    if not isinstance(content, list):
        return len(str(content or "").encode("utf-8"))
    total = 0
    for part in content:
        if not isinstance(part, dict):
            total += len(str(part or "").encode("utf-8"))
            continue
        part_type = str(part.get("type") or "").strip().lower()
        if part_type in {"image_url", "image", "input_image", "audio", "input_audio", "video"}:
            continue
        text = part.get("text")
        if isinstance(text, str):
            total += len(text.encode("utf-8"))
    return total


def _content_media_tokens(content: object) -> int:
    """Flat token estimate for media parts in one message ``content``."""
    if not isinstance(content, list):
        return 0
    images = 0
    for part in content:
        if not isinstance(part, dict):
            continue
        part_type = str(part.get("type") or "").strip().lower()
        if part_type in {"image_url", "image", "input_image"}:
            images += 1
    return images * IMAGE_PROMPT_TOKENS


def _prompt_tokens_from_messages(messages: object) -> int:
    """UTF-8 bytes / 3 for text, plus a flat estimate per attached image.

    Conservative and provider-free, so it stays safe to run at stream preflight.
    """
    if not isinstance(messages, list):
        return 1
    prompt_bytes = 0
    media_tokens = 0
    for message in messages:
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        prompt_bytes += _content_prompt_bytes(content)
        media_tokens += _content_media_tokens(content)
    return max(1, (prompt_bytes + 2) // 3 + media_tokens)


def _completion_tokens_from_body(body: dict) -> int:
    try:
        return max(1, min(8192, int(body.get("max_tokens") or 4096)))
    except (TypeError, ValueError):
        return 4096


def _text_tokens(text: str) -> int:
    encoded = text.encode("utf-8")
    return max(1, (len(encoded) + 2) // 3)


def _locked_user_stmt(user_id: int):
    """``SELECT ... FOR UPDATE`` for a user that also refreshes the ORM instance.

    ``populate_existing=True`` is mandatory here, not cosmetic. ``get_current_user``
    loads the ``User`` through the same request-scoped session before any endpoint
    runs, so the row is already in the identity map. Without the flag SQLAlchemy
    takes the row lock but hands back the *cached* instance, so ``budget_used_usd``
    / ``budget_reserved_usd`` are read from a pre-lock snapshot. A settlement that
    committed in between is then invisible, and writing ``held + amount`` back
    resurrects an already-released hold — which is how ``budget_reserved_usd``
    drifted to $5.05 with zero ``held`` rows and locked the account out.
    """
    return select(User).where(User.id == int(user_id)).with_for_update().execution_options(populate_existing=True)


def _locked_key_stmt(key_id: int):
    """``SELECT ... FOR UPDATE`` for an API key, refreshing the ORM instance.

    Same reasoning as :func:`_locked_user_stmt`.
    """
    return (
        select(AlphaRouterApiKey)
        .where(AlphaRouterApiKey.id == int(key_id))
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def _hold_fits_balance(
    *,
    amount: float,
    limit: float,
    used: float,
    held: float,
) -> bool:
    """Whether the estimated hold still fits inside the remaining balance.

    Admission is strict: an operation may not start unless its whole estimate
    fits. This is the *only* budget control that exists — nothing re-checks the
    balance once a request is running, and an async media job cannot be stopped
    at all — so weakening it has no second line of defence behind it.

    An earlier revision clamped an over-sized estimate down to whatever balance
    was left and admitted the request anyway. That is safe only while the
    estimate grossly over-states the real cost (a chat turn). For a metered job
    it is not: a 30-second video quoted at $7.64 was admitted on a $1.68 hold and
    then settled at its real $6.95, taking a $12.00 budget to $17.27. Estimates
    for video, speech, image, embedding and tool calls are priced from a
    caller-supplied quantity, so they are predictions rather than guesses and
    must be honoured.
    """
    headroom = round(float(limit) - float(used) - float(held), 8)
    return headroom >= float(amount)


def _soft_overshoot_tolerance() -> float:
    """How far a chat estimate may exceed the balance before it is refused."""
    settings = get_settings()
    return max(0.0, float(getattr(settings, "budget_soft_overshoot_usd", 0.5) or 0.0))


def _soft_hold_allowance(
    *,
    amount: float,
    limit: float,
    used: float,
    held: float,
) -> float | None:
    """Hold to take for an operation whose cost cannot be known in advance.

    Only chat qualifies. Its hold assumes the whole ``max_tokens`` budget for the
    reply, so it over-states a short answer by orders of magnitude — a "hi" that
    really costs a fraction of a cent can quote a dollar. Refusing on that number
    turns away users who have genuine budget left, which is the bug this exists to
    prevent.

    So a chat turn may start on a hold clamped down to the balance that is
    actually left, but only while the estimate misses that balance by no more
    than ``budget_soft_overshoot_usd``. Because the estimate is an upper bound for
    chat, bounding the shortfall also bounds the real overshoot — the risk is
    explicit and configurable instead of unlimited.

    This must never be applied to video, speech, image, embedding or tool calls:
    those are priced from a caller-supplied quantity, so their estimate is a
    prediction, and clamping it is what let a 30-second video take a $12.00 budget
    to $17.27. Returns the hold to take, or ``None`` to refuse.
    """
    headroom = round(float(limit) - float(used) - float(held), 8)
    if headroom <= 0:
        return None
    shortfall = round(float(amount) - headroom, 8)
    if shortfall <= 0:
        return float(amount)
    if shortfall > _soft_overshoot_tolerance():
        return None
    return headroom


def _exhausted_detail(
    *,
    amount: float,
    limit: float,
    used: float,
    held: float,
    base_detail: str,
    scope_label: str,
) -> str:
    """Rejection message naming the estimate and the balance actually left.

    Without these numbers a refusal is indistinguishable from a bug: a bare
    "Monthly budget exceeded" gave no way to tell a spent budget from an
    over-sized estimate or a drifted reserved counter.
    """
    headroom = round(float(limit) - float(used) - float(held), 8)
    if headroom <= 0:
        return base_detail
    return (
        f"{base_detail} This request is estimated at ${float(amount):.4f} but only "
        f"${headroom:.4f} of {scope_label} remains."
    )


async def _admit_hold(
    db: AsyncSession,
    *,
    subject_type: str,
    subject_id: int,
    amount: float,
    limit: float,
    used: float,
    held: float,
    cost_is_estimated: bool,
    base_detail: str,
    scope_label: str,
) -> tuple[float, float]:
    """Decide whether this hold may be taken, repairing counter drift first.

    Two admission policies, chosen by whether the cost is knowable in advance:

    * ``cost_is_estimated=False`` (video, speech, image, embedding, tools) — the
      quantity comes from the request, so the quote is a prediction and the whole
      of it must fit.
    * ``cost_is_estimated=True`` (chat) — the reply length is unknown, so the
      quote is an upper bound and may be clamped to the remaining balance within
      ``budget_soft_overshoot_usd``.

    Either way, a refusal is checked twice. ``budget_reserved_usd`` /
    ``period_reserved_usd`` are running counters kept in step with the open
    ``held`` rows, and they can drift *above* them — at which point the subject is
    locked out for the rest of the period, because ``expire_stale_reservations``
    only releases rows and a counter with no rows behind it has nothing to
    release. Observed in production: a user showing $10.29 of a $15.00 budget was
    refused every message because $5.05 was pinned in the counter with **zero**
    ``held`` rows. So before refusing, reconcile against the rows that actually
    exist and re-decide.

    Returns the (possibly repaired) held total and the hold to take, or raises 402.
    """

    def evaluate(current_held: float) -> float | None:
        if cost_is_estimated:
            return _soft_hold_allowance(amount=amount, limit=limit, used=used, held=current_held)
        return amount if _hold_fits_balance(amount=amount, limit=limit, used=used, held=current_held) else None

    allowed = evaluate(held)
    if allowed is None and held > 0:
        repaired = await reconcile_subject_reserved(db, subject_type, int(subject_id))
        if repaired < held:
            held = repaired
            allowed = evaluate(held)
    if allowed is None:
        raise HTTPException(
            status_code=402,
            detail=_exhausted_detail(
                amount=amount,
                limit=limit,
                used=used,
                held=held,
                base_detail=base_detail,
                scope_label=scope_label,
            ),
        )
    return held, round(float(allowed), 8)


def _code_interpreter_requested(body: dict | None) -> bool:
    tools = (body or {}).get("tools") or {}
    return isinstance(tools, dict) and bool(tools.get("code_interpreter"))


async def reservation_hold_usd(
    db: AsyncSession,
    *,
    service_type: str,
    ai_model: AIModel | None = None,
    provider_type: str | None = None,
    model_id: str | None = None,
    connection_id: int | None = None,
    quantity: float | None = None,
    unit: str | None = None,
    body: dict | None = None,
) -> float:
    """Single hold amount for any paid operation (chat, image, video, speech, tools)."""
    from app.services.usage_accounting_service import quote_hold

    service = (service_type or "unknown").strip().lower() or "unknown"
    if service in {"chat", "completion"}:
        service = "llm"
    prompt_tokens = None
    completion_tokens = None
    qty = quantity
    qty_unit = unit
    if body and service == "llm":
        prompt_tokens = _prompt_tokens_from_messages(body.get("messages"))
        completion_tokens = _completion_tokens_from_body(body)
    elif body and service == "embedding":
        prompt_tokens = _text_tokens(str(body.get("input") or ""))
        qty = float(prompt_tokens)
        qty_unit = "token"
    quoted = await quote_hold(
        db,
        service_type=service,
        ai_model=ai_model,
        provider_type=provider_type,
        model_id=model_id or getattr(ai_model, "external_id", None),
        connection_id=connection_id if connection_id is not None else getattr(ai_model, "connection_id", None),
        quantity=qty,
        unit=qty_unit,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
    )
    total = float(quoted.hold_usd)
    if _code_interpreter_requested(body):
        extra = await quote_hold(
            db,
            service_type="tool",
            ai_model=ai_model,
            provider_type=provider_type,
            model_id=model_id or getattr(ai_model, "external_id", None),
            connection_id=connection_id if connection_id is not None else getattr(ai_model, "connection_id", None),
            quantity=1.0,
            unit="request",
        )
        total += float(extra.hold_usd)
    return round(total, 8)


def estimate_chat_hold(ai_model: AIModel, body: dict) -> float:
    """Estimate a hold without blocking stream start on model tokenization."""
    settings = get_settings()
    fallback = float(settings.budget_chat_fallback_hold_usd or 0.05)
    messages = body.get("messages")
    if isinstance(messages, list):
        # UTF-8 bytes / 3 is deliberately conservative for both Latin and
        # multi-byte scripts while remaining O(input size) and provider-free.
        prompt_bytes = sum(
            len(str(message.get("content") or "").encode("utf-8")) for message in messages if isinstance(message, dict)
        )
    else:
        prompt_bytes = 0
    prompt_tokens = max(1, (prompt_bytes + 2) // 3)
    try:
        output_tokens = max(1, min(8192, int(body.get("max_tokens") or 4096)))
    except (TypeError, ValueError):
        output_tokens = 4096
    in_rate = _positive_float(ai_model.input_cost_per_1k, 0.0)
    out_rate = _positive_float(ai_model.output_cost_per_1k, 0.0)
    priced_estimate = (prompt_tokens / 1000) * in_rate + (output_tokens / 1000) * out_rate
    estimate = max(fallback, priced_estimate * 1.25)
    tools = body.get("tools") or {}
    if isinstance(tools, dict) and tools.get("code_interpreter"):
        estimate *= 4
    return _clamp_hold(estimate, fallback)


def estimate_embedding_hold(ai_model: AIModel, body: dict) -> float:
    settings = get_settings()
    fallback = float(settings.budget_embedding_fallback_hold_usd or 0.01)
    try:
        prompt_tokens = int(litellm.token_counter(model=ai_model.external_id, text=str(body.get("input") or "")) or 0)
    except Exception:
        prompt_tokens = 0
    in_rate = _positive_float(ai_model.input_cost_per_1k, 0.0)
    return _clamp_hold((prompt_tokens / 1000) * in_rate * 1.25, fallback)


def estimate_image_hold(ai_model: AIModel | None, *, quantity: int = 1) -> float:
    del ai_model
    settings = get_settings()
    return _clamp_hold(
        float(settings.budget_image_fallback_hold_usd or 0.25) * max(1, int(quantity or 1)),
        0.25,
    )


_VIDEO_RESOLUTION_HOLD_FACTOR = {
    "480p": 0.75,
    "720p": 1.0,
    "1080p": 1.5,
    "1k": 1.5,
    "2k": 2.0,
    "4k": 3.0,
}


def estimate_video_hold(
    ai_model: AIModel | None,
    *,
    duration_seconds: int = 4,
    resolution: str | None = "720p",
) -> float:
    """Conservative hold for async video generation (duration × resolution tier)."""
    del ai_model
    settings = get_settings()
    base = float(settings.budget_video_fallback_hold_usd or 1.50)
    try:
        duration = max(1, int(duration_seconds or 0))
    except (TypeError, ValueError):
        duration = 1
    res_key = (resolution or "720p").strip().lower()
    factor = float(_VIDEO_RESOLUTION_HOLD_FACTOR.get(res_key, 1.0))
    # Scale from a 4-second baseline clip.
    amount = base * (duration / 4.0) * factor
    return _clamp_hold(amount, base)


def estimate_metered_service_hold(service_type: str) -> float:
    """Conservative hold for non-token services without a quoted maximum."""

    settings = get_settings()
    service = (service_type or "").strip().lower()
    if service in {"audio", "transcription", "speech"}:
        fallback = float(settings.budget_audio_fallback_hold_usd or 0.10)
    else:
        fallback = float(settings.budget_tool_fallback_hold_usd or 0.05)
    return _clamp_hold(fallback, fallback)


def estimate_speech_hold(ai_model: AIModel | None, *, characters: int = 1) -> float:
    """Conservative hold for synchronous text-to-speech generation."""
    del ai_model
    settings = get_settings()
    base = float(settings.budget_audio_fallback_hold_usd or 0.10)
    # Scale linearly with character count; 1000 chars ~= one base unit.
    factor = max(1.0, (max(1, int(characters or 1)) / 1000.0))
    return _clamp_hold(base * factor, base)


def reservation_key(body: dict, *, operation: str) -> str:
    explicit = body.get("_idempotency_key") or body.get("assistant_client_message_id") or ""
    if explicit:
        return f"{operation}:{str(explicit).strip()[:128]}"
    return f"{operation}:{uuid.uuid4()}"


async def _existing_reservation(
    db: AsyncSession,
    key: str,
) -> BudgetReservation | None:
    return (
        await db.execute(select(BudgetReservation).where(BudgetReservation.idempotency_key == key))
    ).scalar_one_or_none()


async def reserve(
    db: AsyncSession,
    *,
    user_id: int | None,
    alpha_router_api_key_id: int | None,
    amount_usd: float,
    operation: str,
    model_id: str,
    idempotency_key: str,
    cost_is_estimated: bool = False,
) -> BudgetReservation | None:
    """Take an in-flight hold against a user budget or API-key credit.

    ``cost_is_estimated`` selects the admission policy and defaults to the strict
    one, so a new caller is safe by omission. Pass ``True`` only for chat, whose
    reply length — and therefore cost — cannot be known before the call. See
    :func:`_admit_hold`.
    """
    if user_id is None and alpha_router_api_key_id is None:
        return None
    subject_type = SUBJECT_ALPHA_ROUTER_KEY if alpha_router_api_key_id is not None else SUBJECT_USER
    subject_id = int(alpha_router_api_key_id if alpha_router_api_key_id is not None else user_id)
    scoped_key = f"{subject_type}:{subject_id}:{idempotency_key}"[:160]
    # No upper cap here. Every caller derives ``amount_usd`` from
    # ``reservation_hold_usd`` -> ``quote_hold``, which already bounds an
    # *unpriced* estimate to the small global fallback. Re-clamping to
    # ``budget_max_hold_usd`` on top of that only truncated *priced* quotes —
    # contradicting quote_hold's documented contract ("priced holds ... are not
    # clamped to the unpriced maximum") and under-reserving the expensive jobs
    # that need the ceiling most: a 30-second video quoted at $7.64 was held at
    # $5.00, so it could overshoot the budget even when admission was strict.
    amount = round(max(0.0001, float(amount_usd or 0)), 8)
    if alpha_router_api_key_id is not None:
        key = (await db.execute(_locked_key_stmt(alpha_router_api_key_id))).scalar_one_or_none()
        if key is None:
            raise HTTPException(status_code=401, detail="Invalid API key")
        await ensure_key_usable(db, key)
        if await _existing_reservation(db, scoped_key):
            raise HTTPException(status_code=409, detail="Duplicate request idempotency key")
        limit = float(key.credit_limit_usd or 0)
        used = float(key.period_used_usd or 0)
        held = float(key.period_reserved_usd or 0)
        # ensure_key_usable has already refused limit <= 0 unless the key is
        # explicitly unlimited, so "limit > 0" here means "a cap applies".
        if limit > 0:
            held, amount = await _admit_hold(
                db,
                subject_type=subject_type,
                subject_id=subject_id,
                amount=amount,
                limit=limit,
                used=used,
                held=held,
                cost_is_estimated=cost_is_estimated,
                base_detail="API key credit limit exceeded for this period.",
                scope_label="key credit",
            )
        key.period_reserved_usd = round(held + amount, 8)
    else:
        user = (await db.execute(_locked_user_stmt(user_id))).scalar_one_or_none()
        if user is None or not user.is_active:
            raise HTTPException(status_code=403, detail="Account disabled")
        await ensure_budget_period(db, user)
        if await _existing_reservation(db, scoped_key):
            raise HTTPException(status_code=409, detail="Duplicate request idempotency key")
        limit = float(user.monthly_budget_usd or 0)
        used = float(user.budget_used_usd or 0)
        held = float(user.budget_reserved_usd or 0)
        if limit <= 0:
            raise HTTPException(status_code=402, detail=NO_PLAN_BUDGET_DETAIL)
        held, amount = await _admit_hold(
            db,
            subject_type=subject_type,
            subject_id=subject_id,
            amount=amount,
            limit=limit,
            used=used,
            held=held,
            cost_is_estimated=cost_is_estimated,
            base_detail=f"{BUDGET_EXCEEDED_DETAIL}.",
            scope_label="monthly budget",
        )
        user.budget_reserved_usd = round(held + amount, 8)

    settings = get_settings()
    ttl = max(900, min(86400, int(settings.budget_reservation_ttl_seconds or 7200)))
    row = BudgetReservation(
        id=str(uuid.uuid4()),
        subject_type=subject_type,
        subject_id=subject_id,
        idempotency_key=scoped_key,
        operation=operation,
        model_id=model_id,
        reserved_usd=amount,
        status=STATUS_HELD,
        created_at=_now(),
        expires_at=_now() + datetime.timedelta(seconds=ttl),
    )
    db.add(row)
    await db.flush()
    return row


async def _lock_reservation(
    db: AsyncSession,
    reservation_id: str,
) -> BudgetReservation | None:
    return (
        await db.execute(
            select(BudgetReservation)
            .where(BudgetReservation.id == reservation_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()


async def _lock_subject(
    db: AsyncSession,
    subject_type: str,
    subject_id: int,
) -> bool:
    if subject_type == SUBJECT_USER:
        return (await db.execute(_locked_user_stmt(subject_id))).scalar_one_or_none() is not None
    if subject_type == SUBJECT_ALPHA_ROUTER_KEY:
        return (await db.execute(_locked_key_stmt(subject_id))).scalar_one_or_none() is not None
    return False


async def _lock_subject_then_reservation(
    db: AsyncSession,
    reservation_id: str,
) -> BudgetReservation | None:
    probe = await db.get(BudgetReservation, reservation_id)
    if probe is None:
        return None
    if not await _lock_subject(db, probe.subject_type, int(probe.subject_id)):
        return None
    return await _lock_reservation(db, reservation_id)


async def _apply_release_to_subject(
    db: AsyncSession,
    row: BudgetReservation,
    *,
    actual_usd: float | None,
) -> None:
    reserved = max(0.0, float(row.reserved_usd or 0))
    actual = max(0.0, float(actual_usd or 0))
    if row.subject_type == SUBJECT_USER:
        user = (await db.execute(_locked_user_stmt(row.subject_id))).scalar_one_or_none()
        if user:
            user.budget_reserved_usd = round(
                max(0.0, float(user.budget_reserved_usd or 0) - reserved),
                8,
            )
            if actual_usd is not None:
                user.budget_used_usd = round(
                    float(user.budget_used_usd or 0) + actual,
                    8,
                )
    elif row.subject_type == SUBJECT_ALPHA_ROUTER_KEY:
        key = (await db.execute(_locked_key_stmt(row.subject_id))).scalar_one_or_none()
        if key:
            key.period_reserved_usd = round(
                max(0.0, float(key.period_reserved_usd or 0) - reserved),
                8,
            )
            if actual_usd is not None:
                key.period_used_usd = round(
                    float(key.period_used_usd or 0) + actual,
                    8,
                )
                key.total_used_usd = round(
                    float(key.total_used_usd or 0) + actual,
                    8,
                )
                key.last_used_at = _now()


async def settle(
    db: AsyncSession,
    reservation_id: str,
    *,
    actual_usd: float,
    request_log_id: int | None = None,
) -> bool:
    row = await _lock_subject_then_reservation(db, reservation_id)
    if row is None or row.status != STATUS_HELD:
        return False
    actual = max(0.0, float(actual_usd or 0))
    await _apply_release_to_subject(db, row, actual_usd=actual)
    row.actual_usd = actual
    row.status = STATUS_SETTLED
    row.request_log_id = request_log_id
    row.settled_at = _now()
    await db.flush()
    return True


async def release(
    db: AsyncSession,
    reservation_id: str,
    *,
    expired: bool = False,
) -> bool:
    row = await _lock_subject_then_reservation(db, reservation_id)
    if row is None or row.status != STATUS_HELD:
        return False
    await _apply_release_to_subject(db, row, actual_usd=None)
    row.status = STATUS_EXPIRED if expired else STATUS_RELEASED
    row.settled_at = _now()
    await db.flush()
    return True


async def expire_stale_reservations(db: AsyncSession) -> int:
    reservation_ids = (
        (
            await db.execute(
                select(BudgetReservation.id).where(
                    BudgetReservation.status == STATUS_HELD,
                    BudgetReservation.expires_at < _now(),
                )
            )
        )
        .scalars()
        .all()
    )
    expired = 0
    for reservation_id in reservation_ids:
        if await release(db, reservation_id, expired=True):
            expired += 1
    return expired


async def reconcile_subject_reserved(
    db: AsyncSession,
    subject_type: str,
    subject_id: int,
) -> float:
    """Set the subject reserved counter to the sum of open HELD rows.

    Lock *first*, sum *second*. ``reserve`` holds the subject row FOR UPDATE
    while it inserts the reservation and bumps the counter in one
    transaction. Summing before taking that lock reads a snapshot without the
    in-flight row, then waits for the lock, then writes the stale sum over
    the counter the reservation just increased - the hold exists but is no
    longer counted, so the subject can overspend by exactly that amount.
    """
    if subject_type == SUBJECT_USER:
        subject = (await db.execute(_locked_user_stmt(subject_id))).scalar_one_or_none()
    elif subject_type == SUBJECT_ALPHA_ROUTER_KEY:
        subject = (await db.execute(_locked_key_stmt(subject_id))).scalar_one_or_none()
    else:
        subject = None
    held = float(
        (
            await db.execute(
                select(func.coalesce(func.sum(BudgetReservation.reserved_usd), 0.0)).where(
                    BudgetReservation.subject_type == subject_type,
                    BudgetReservation.subject_id == subject_id,
                    BudgetReservation.status == STATUS_HELD,
                )
            )
        ).scalar_one()
    )
    held = round(max(0.0, held), 8)
    if subject is not None:
        if subject_type == SUBJECT_USER:
            subject.budget_reserved_usd = held
        else:
            subject.period_reserved_usd = held
    await db.flush()
    return held


async def _drifted_subject_ids(
    db: AsyncSession,
    *,
    subject_type: str,
    counter_column,
    id_column,
    tolerance: float = 1e-6,
) -> list[int]:
    """Subject ids whose reserved counter sits above their open ``held`` rows."""
    held_totals = (
        select(
            BudgetReservation.subject_id.label("sid"),
            func.coalesce(func.sum(BudgetReservation.reserved_usd), 0.0).label("held_sum"),
        )
        .where(
            BudgetReservation.subject_type == subject_type,
            BudgetReservation.status == STATUS_HELD,
        )
        .group_by(BudgetReservation.subject_id)
        .subquery()
    )
    rows = (
        await db.execute(
            select(
                id_column,
                counter_column,
                func.coalesce(held_totals.c.held_sum, 0.0),
            )
            .outerjoin(held_totals, held_totals.c.sid == id_column)
            .where(counter_column > tolerance)
        )
    ).all()
    return [
        int(subject_id)
        for subject_id, counter, held_sum in rows
        if float(counter or 0) - float(held_sum or 0) > tolerance
    ]


async def reconcile_drifted_reserved_counters(db: AsyncSession) -> int:
    """Repair every reserved counter that sits above its open ``held`` rows.

    Companion to :func:`expire_stale_reservations`: that one closes rows whose
    lease ran out, this one closes the gap a *counter* can develop when a
    decrement is lost. The two are complementary — a counter with no rows behind
    it has nothing to expire, so without this it stays inflated (and keeps
    consuming budget) until period rollover.

    Returns the number of subjects repaired.

    Only one instance may run this at a time: the scheduler leader election
    already guarantees that, and the transaction-scoped advisory lock below
    is the defence in depth for a manual run or a second deployment sharing
    the database. When the lock is taken elsewhere this call returns 0.
    """
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        got = (
            await db.execute(
                text("SELECT pg_try_advisory_xact_lock(:lock_id)"),
                {"lock_id": RECONCILE_LOCK_ID},
            )
        ).scalar()
        if not got:
            return 0
    repaired = 0
    for subject_type, id_column, counter_column in (
        (SUBJECT_USER, User.id, User.budget_reserved_usd),
        (
            SUBJECT_ALPHA_ROUTER_KEY,
            AlphaRouterApiKey.id,
            AlphaRouterApiKey.period_reserved_usd,
        ),
    ):
        subject_ids = await _drifted_subject_ids(
            db,
            subject_type=subject_type,
            counter_column=counter_column,
            id_column=id_column,
        )
        for subject_id in subject_ids:
            await reconcile_subject_reserved(db, subject_type, subject_id)
            repaired += 1
    return repaired


async def release_open_holds_for_subject(
    db: AsyncSession,
    subject_type: str,
    subject_id: int,
) -> int:
    """Expire all open holds for a subject (used on budget/credit period rollover).

    Prevents month/period resets from leaving ``budget_reserved_usd`` /
    ``period_reserved_usd`` out of sync with reservation rows. In-flight
    requests that finish later charge via the settle-miss fallback on the new
    period instead of mutating a stale hold.
    """
    await _lock_subject(db, subject_type, int(subject_id))
    rows = (
        (
            await db.execute(
                select(BudgetReservation)
                .where(
                    BudgetReservation.subject_type == subject_type,
                    BudgetReservation.subject_id == int(subject_id),
                    BudgetReservation.status == STATUS_HELD,
                )
                .with_for_update()
            )
        )
        .scalars()
        .all()
    )
    released = 0
    for row in rows:
        if await release(db, row.id, expired=True):
            released += 1
    await reconcile_subject_reserved(db, subject_type, int(subject_id))
    return released
