"""Raw provider payloads are kept on a clock the operator sets.

They are what explains a failure, and also the bulkiest thing in the log
tables (a provider can echo the whole prompt back), so the API Logs page owns
their lifetime: cleared after N days while the rows — costs, tokens, status,
the failure reason — stay as long as the request log itself.
"""

from __future__ import annotations

import datetime

from app.models.cost_accounting import UsageEvent
from app.models.video import VideoGenerationJob
from app.services.log_detail_retention_service import (
    DEFAULT_RETENTION_DAYS,
    MAX_RETENTION_DAYS,
    clamp_retention_days,
    get_raw_payload_retention,
    purge_expired_raw_payloads,
    set_raw_payload_retention_days,
)


def test_retention_days_are_clamped_to_a_sane_window():
    assert clamp_retention_days(0) == 1
    assert clamp_retention_days(-5) == 1
    assert clamp_retention_days(10_000) == MAX_RETENTION_DAYS
    assert clamp_retention_days("45") == 45
    assert clamp_retention_days(None) == DEFAULT_RETENTION_DAYS
    assert clamp_retention_days("nonsense") == DEFAULT_RETENTION_DAYS


async def test_default_until_an_operator_sets_it(db_session):
    payload = await get_raw_payload_retention(db_session)
    assert payload["retention_days"] == DEFAULT_RETENTION_DAYS
    assert payload["stored_events"] == 0
    assert payload["expired_events"] == 0

    saved = await set_raw_payload_retention_days(db_session, 7)
    assert saved["retention_days"] == 7
    assert (await get_raw_payload_retention(db_session))["retention_days"] == 7


async def _event(db_session, *, age_days: int, raw: str | None) -> str:
    from app.models.cost_accounting import UsageOperation

    started = datetime.datetime.utcnow() - datetime.timedelta(days=age_days)
    operation = UsageOperation(
        id=f"op-{age_days}-{raw is not None}",
        operation_type="video",
        source="alpha_router_chat",
        status="failed",
        idempotency_key=f"key-{age_days}-{raw is not None}",
        total_cost_usd=0,
        started_at=started,
    )
    db_session.add(operation)
    await db_session.flush()
    event = UsageEvent(
        id=f"ev-{age_days}-{raw is not None}",
        operation_id=operation.id,
        provider_type="openrouter",
        service_type="video",
        operation_name="video:generation",
        idempotency_key=f"evkey-{age_days}-{raw is not None}",
        status="failed",
        raw_usage_json=raw,
        started_at=started,
    )
    db_session.add(event)
    await db_session.flush()
    return event.id


async def test_purge_clears_old_payloads_and_keeps_the_rows(db_session, user):
    old_id = await _event(db_session, age_days=40, raw='{"status":"failed"}')
    recent_id = await _event(db_session, age_days=2, raw='{"status":"completed"}')

    job = VideoGenerationJob(
        id="job-old",
        user_id=user.id,
        model_id="bytedance/seedance-1-pro",
        prompt="a cat",
        operation="generation",
        status="failed",
        provider_status_raw='{"status":"failed"}',
        created_at=datetime.datetime.utcnow() - datetime.timedelta(days=40),
    )
    db_session.add(job)
    await db_session.flush()

    result = await purge_expired_raw_payloads(db_session, days=30)
    await db_session.flush()

    assert result["usage_events_cleared"] == 1
    assert result["video_jobs_cleared"] == 1

    old_event = await db_session.get(UsageEvent, old_id)
    recent_event = await db_session.get(UsageEvent, recent_id)
    await db_session.refresh(old_event)
    await db_session.refresh(recent_event)
    # The row survives — only the verbatim payload goes.
    assert old_event is not None
    assert old_event.raw_usage_json is None
    assert old_event.status == "failed"
    assert recent_event.raw_usage_json == '{"status":"completed"}'

    await db_session.refresh(job)
    assert job.provider_status_raw is None
    assert job.status == "failed"


async def test_shortening_the_window_reports_what_it_will_delete(db_session):
    """The Retention Policy page shows this count before the operator saves."""
    await _event(db_session, age_days=10, raw='{"status":"failed"}')
    await set_raw_payload_retention_days(db_session, 30)
    wide = await get_raw_payload_retention(db_session)
    assert wide["stored_events"] == 1
    assert wide["expired_events"] == 0

    await set_raw_payload_retention_days(db_session, 5)
    narrow = await get_raw_payload_retention(db_session)
    assert narrow["stored_events"] == 1
    assert narrow["expired_events"] == 1
