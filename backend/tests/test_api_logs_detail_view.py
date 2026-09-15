"""API Logs has to answer "why did this fail?" — not just "it failed".

The page used to render a bare "Fail": error_message was fetched and thrown
away, and nothing said whether a row was a chat turn or a video job. These
cover the list payload, the new filters and the detail payload.
"""

from __future__ import annotations

from app.api.logs import _cost_details_payload, _serialize_log_rows
from app.models.logging import RequestLog
from app.services.usage_logging_service import log_usage


async def _failed_video_log(db_session, user) -> int:
    log_id = await log_usage(
        db_session,
        user_id=user.id,
        username=user.username,
        model_id="bytedance/seedance-1-pro",
        prompt_tokens=0,
        completion_tokens=0,
        cached_tokens=0,
        total_cost_usd=0.0,
        response_time_ms=42.0,
        prompt_language="en",
        source_ip="10.0.0.1",
        source="alpha_router_chat",
        success=False,
        error_message="Upstream timed out (ReadTimeout) (GET https://cdn.example.com/v/1.mp4)",
        error_code="timeout",
        correlation_id="job-77",
        provider_job_id="vid_77",
        operation_type="video",
    )
    await db_session.commit()
    return log_id


async def test_list_rows_carry_the_failure_detail_and_the_operation_type(db_session, user) -> None:
    log_id = await _failed_video_log(db_session, user)
    row = await db_session.get(RequestLog, log_id)

    [item] = await _serialize_log_rows(db_session, [row])

    assert item["success"] is False
    assert item["error_code"] == "timeout"
    assert "ReadTimeout" in item["error_message"]
    assert item["correlation_id"] == "job-77"
    assert item["provider_job_id"] == "vid_77"
    # Without this an admin cannot tell a video job from a chat turn in the list.
    assert item["operation_type"] == "video"


async def test_detail_payload_exposes_the_request_block(db_session, user) -> None:
    log_id = await _failed_video_log(db_session, user)
    row = await db_session.get(RequestLog, log_id)

    payload = await _cost_details_payload(db_session, row)

    request = payload["request"]
    assert request["error_code"] == "timeout"
    assert request["provider_job_id"] == "vid_77"
    assert request["correlation_id"] == "job-77"
    assert request["success"] is False
    assert payload["operation"]["operation_type"] == "video"
    # Attempt rows gained the connection and the timing window.
    for event in payload["events"]:
        assert "connection_id" in event
        assert "started_at" in event


async def test_filters_narrow_by_operation_type_and_error_code(db_session, user) -> None:
    """The admin endpoint sits behind the IP-guard middleware, so this drives
    the payload builder the endpoint calls."""
    from app.api.logs import _logs_list_payload

    await _failed_video_log(db_session, user)
    await log_usage(
        db_session,
        user_id=user.id,
        username=user.username,
        model_id="openai/gpt-4o",
        prompt_tokens=10,
        completion_tokens=5,
        cached_tokens=0,
        total_cost_usd=0.01,
        response_time_ms=100.0,
        prompt_language="en",
        source_ip=None,
        source="alpha_router_chat",
        success=True,
        operation_type="chat",
    )
    await db_session.commit()

    everything = await _logs_list_payload(db_session, limit=50)
    assert {item["operation_type"] for item in everything["items"]} == {"video", "chat"}

    only_video = await _logs_list_payload(db_session, limit=50, operation_type="video")
    assert only_video["items"], "the video row should survive the filter"
    assert {item["operation_type"] for item in only_video["items"]} == {"video"}

    timeouts = await _logs_list_payload(db_session, limit=50, error_code="timeout")
    assert timeouts["items"]
    assert all(item["error_code"] == "timeout" for item in timeouts["items"])

    none_left = await _logs_list_payload(db_session, limit=50, error_code="connect_error")
    assert none_left["items"] == []


async def test_export_carries_the_same_detail_as_the_page(db_session, user) -> None:
    """Whatever the page shows, the Export button has to hand over too."""
    from app.models.logging import RequestLog as RL
    from app.services.log_export_service import (
        dataframe_to_csv_bytes,
        request_logs_to_export_dataframe,
        resolve_operation_types,
    )

    log_id = await _failed_video_log(db_session, user)
    row = await db_session.get(RL, log_id)

    df = request_logs_to_export_dataframe(
        [row],
        tz_mode="utc",
        provider_map={},
        key_map={},
        operation_types=await resolve_operation_types(db_session, [row]),
    )
    assert list(df["Type"]) == ["video"]
    assert list(df["Error Code"]) == ["timeout"]
    assert list(df["Correlation Id"]) == ["job-77"]
    assert list(df["Provider Job Id"]) == ["vid_77"]
    assert "ReadTimeout" in df["Error"].iloc[0]

    csv_text = dataframe_to_csv_bytes(df).decode("utf-8")
    for header in ("Type", "Error Code", "HTTP Status", "Error", "Correlation Id", "Provider Job Id"):
        assert header in csv_text


async def test_the_user_facing_payload_withholds_the_operating_internals(db_session, user) -> None:
    """The same builder serves the chat cost modal; it must not leak operator detail.

    `/user/request-logs/{id}/cost-details` is reachable by any signed-in user
    for their own request, and it shares `_cost_details_payload` with the admin
    API Logs page. When the failure-detail work added the provider's verbatim
    response and the tracing ids, they reached that endpoint too.
    """
    log_id = await _failed_video_log(db_session, user)
    row = await db_session.get(RequestLog, log_id)

    operator = await _cost_details_payload(db_session, row)
    owner = await _cost_details_payload(db_session, row, operator_detail=False)

    # Why it failed is the user's business.
    assert owner["request"]["error_code"] == "timeout"
    assert owner["request"]["error_message"] == operator["request"]["error_message"]
    assert owner["request"]["http_status"] == operator["request"]["http_status"]

    # How we run is not.
    for field in ("correlation_id", "provider_job_id", "source_ip"):
        assert field in operator["request"], field
        assert field not in owner["request"], field

    for event in owner["events"]:
        assert "raw_usage" not in event
        assert "connection_id" not in event


async def test_the_user_route_asks_for_the_narrow_payload(db_session, user) -> None:
    """Guard the wiring, not just the builder."""
    import inspect

    from app.api import logs

    source = inspect.getsource(logs.user_request_log_cost_details)
    assert "operator_detail=False" in source
    assert "operator_detail" not in inspect.getsource(logs.admin_log_cost_details)
