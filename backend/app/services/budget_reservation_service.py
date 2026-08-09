"""Atomic reservations for user budgets and Alpharouter API-key credit."""

from __future__ import annotations

import datetime
import uuid

import litellm
from fastapi import HTTPException
from sqlalchemy import func, select
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


def estimate_chat_hold(ai_model: AIModel, body: dict) -> float:
    """Estimate a hold without blocking stream start on model tokenization."""
    settings = get_settings()
    fallback = float(settings.budget_chat_fallback_hold_usd or 0.05)
    messages = body.get("messages")
    if isinstance(messages, list):
        # UTF-8 bytes / 3 is deliberately conservative for both Latin and
        # multi-byte scripts while remaining O(input size) and provider-free.
        prompt_bytes = sum(
            len(str(message.get("content") or "").encode("utf-8"))
            for message in messages
            if isinstance(message, dict)
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
        prompt_tokens = int(
            litellm.token_counter(model=ai_model.external_id, text=str(body.get("input") or ""))
            or 0
        )
    except Exception:
        prompt_tokens = 0
    in_rate = _positive_float(ai_model.input_cost_per_1k, 0.0)
    return _clamp_hold((prompt_tokens / 1000) * in_rate * 1.25, fallback)


def estimate_image_hold(ai_model: AIModel | None, *, quantity: int = 1) -> float:
    del ai_model
    settings = get_settings()
    return _clamp_hold(
        float(settings.budget_image_fallback_hold_usd or 0.25)
        * max(1, int(quantity or 1)),
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
    duration = max(1, min(int(duration_seconds or 4), int(settings.video_max_duration_seconds or 8)))
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


def reservation_key(body: dict, *, operation: str) -> str:
    explicit = (
        body.get("_idempotency_key")
        or body.get("assistant_client_message_id")
        or ""
    )
    if explicit:
        return f"{operation}:{str(explicit).strip()[:128]}"
    return f"{operation}:{uuid.uuid4()}"


async def _existing_reservation(
    db: AsyncSession,
    key: str,
) -> BudgetReservation | None:
    return (
        await db.execute(
            select(BudgetReservation).where(BudgetReservation.idempotency_key == key)
        )
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
) -> BudgetReservation | None:
    if user_id is None and alpha_router_api_key_id is None:
        return None
    subject_type = (
        SUBJECT_ALPHA_ROUTER_KEY
        if alpha_router_api_key_id is not None
        else SUBJECT_USER
    )
    subject_id = int(
        alpha_router_api_key_id if alpha_router_api_key_id is not None else user_id
    )
    scoped_key = f"{subject_type}:{subject_id}:{idempotency_key}"[:160]
    amount = _clamp_hold(amount_usd, 0.01)
    if alpha_router_api_key_id is not None:
        key = (
            await db.execute(
                select(AlphaRouterApiKey)
                .where(AlphaRouterApiKey.id == alpha_router_api_key_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if key is None:
            raise HTTPException(status_code=401, detail="Invalid API key")
        await ensure_key_usable(db, key)
        if await _existing_reservation(db, scoped_key):
            raise HTTPException(status_code=409, detail="Duplicate request idempotency key")
        limit = float(key.credit_limit_usd or 0)
        used = float(key.period_used_usd or 0)
        held = float(key.period_reserved_usd or 0)
        if limit > 0 and used + held + amount > limit:
            raise HTTPException(status_code=402, detail="API key credit limit exceeded for this period")
        key.period_reserved_usd = round(held + amount, 8)
    else:
        user = (
            await db.execute(
                select(User).where(User.id == user_id).with_for_update()
            )
        ).scalar_one_or_none()
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
        if used + held + amount > limit:
            raise HTTPException(status_code=402, detail=BUDGET_EXCEEDED_DETAIL)
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
        return (
            await db.execute(
                select(User).where(User.id == subject_id).with_for_update()
            )
        ).scalar_one_or_none() is not None
    if subject_type == SUBJECT_ALPHA_ROUTER_KEY:
        return (
            await db.execute(
                select(AlphaRouterApiKey)
                .where(AlphaRouterApiKey.id == subject_id)
                .with_for_update()
            )
        ).scalar_one_or_none() is not None
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
        user = (
            await db.execute(
                select(User).where(User.id == row.subject_id).with_for_update()
            )
        ).scalar_one_or_none()
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
        key = (
            await db.execute(
                select(AlphaRouterApiKey)
                .where(AlphaRouterApiKey.id == row.subject_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
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
        await db.execute(
            select(BudgetReservation.id)
            .where(
                BudgetReservation.status == STATUS_HELD,
                BudgetReservation.expires_at < _now(),
            )
        )
    ).scalars().all()
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
    """Set the subject reserved counter to the sum of open HELD rows."""
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
    if subject_type == SUBJECT_USER:
        user = (
            await db.execute(
                select(User).where(User.id == subject_id).with_for_update()
            )
        ).scalar_one_or_none()
        if user:
            user.budget_reserved_usd = held
    elif subject_type == SUBJECT_ALPHA_ROUTER_KEY:
        key = (
            await db.execute(
                select(AlphaRouterApiKey)
                .where(AlphaRouterApiKey.id == subject_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if key:
            key.period_reserved_usd = held
    await db.flush()
    return held


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
        await db.execute(
            select(BudgetReservation)
            .where(
                BudgetReservation.subject_type == subject_type,
                BudgetReservation.subject_id == int(subject_id),
                BudgetReservation.status == STATUS_HELD,
            )
            .with_for_update()
        )
    ).scalars().all()
    released = 0
    for row in rows:
        if await release(db, row.id, expired=True):
            released += 1
    await reconcile_subject_reserved(db, subject_type, int(subject_id))
    return released
