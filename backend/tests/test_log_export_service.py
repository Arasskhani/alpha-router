"""API Logs CSV export helpers."""

from datetime import datetime
from types import SimpleNamespace

from app.services.log_export_service import (
    ACTIVITY_LOG_COLUMNS,
    DETAIL_LOG_COLUMNS,
    dataframe_to_csv_bytes,
    detail_rows_to_csv_bytes,
    log_row_to_export,
    request_log_detail_to_export_rows,
    request_logs_to_export_dataframe,
)


def test_log_row_export_includes_identity_and_duration():
    row = SimpleNamespace(
        id=42,
        request_time=datetime(2026, 8, 7, 12, 0, 0),
        username="alice",
        source="alpha_router_chat",
        client_app=None,
        alpha_router_api_key_id=None,
        model_id="openai/gpt-4o-mini",
        prompt_tokens=10,
        completion_tokens=5,
        cached_tokens=2,
        total_cost_usd=0.012345,
        provider_cost_usd=0.01,
        calculated_cost_usd=0.012,
        cost_source="provider_response",
        cost_confidence="exact",
        has_unpriced_usage=False,
        response_time_ms=123.4,
        success=True,
        source_ip="127.0.0.1",
        prompt_language="en",
    )
    exported = log_row_to_export(
        row,
        tz_mode="utc",
        provider="openai",
        router_key=None,
    )
    assert exported["Id"] == 42
    assert exported["User"] == "alice (Chat)"
    assert exported["Duration ms"] == 123.4
    assert exported["Cost Confidence"] == "exact"
    assert "Duration ms" in ACTIVITY_LOG_COLUMNS
    assert "Latency ms" not in ACTIVITY_LOG_COLUMNS


def test_filtered_logs_csv_has_bom_and_header():
    row = SimpleNamespace(
        id=1,
        request_time=datetime(2026, 8, 7, 12, 0, 0),
        username="bob",
        source="gateway",
        client_app="Cursor",
        alpha_router_api_key_id=7,
        model_id="gpt-4o-mini",
        prompt_tokens=1,
        completion_tokens=2,
        cached_tokens=0,
        total_cost_usd=0.1,
        provider_cost_usd=None,
        calculated_cost_usd=0.1,
        cost_source="provider_catalog",
        cost_confidence="calculated",
        has_unpriced_usage=False,
        response_time_ms=10,
        success=True,
        source_ip="10.0.0.1",
        prompt_language="fa",
    )
    key = SimpleNamespace(id=7, name="ci-bot", key_prefix="sk-ar")
    df = request_logs_to_export_dataframe(
        [row],
        tz_mode="utc",
        provider_map={"gpt-4o-mini": "openai"},
        key_map={7: key},
    )
    raw = dataframe_to_csv_bytes(df)
    text = raw.decode("utf-8-sig")
    assert text.startswith("Id,Time,User,")
    assert "ci-bot (Gateway API Key)" in text
    assert "Duration ms" in text


def test_personal_api_key_export_shows_username_not_key_name():
    row = SimpleNamespace(
        id=2,
        request_time=datetime(2026, 8, 17, 12, 0, 0),
        username="majid",
        source="user_key",
        client_app="Kilo Code",
        alpha_router_api_key_id=None,
        user_api_key_id=4,
        model_id="gpt-4o-mini",
        prompt_tokens=1,
        completion_tokens=2,
        cached_tokens=0,
        total_cost_usd=0.1,
        provider_cost_usd=None,
        calculated_cost_usd=0.1,
        cost_source="provider_catalog",
        cost_confidence="calculated",
        has_unpriced_usage=False,
        response_time_ms=10,
        success=True,
        source_ip="10.0.0.1",
        prompt_language="en",
    )
    user_key = SimpleNamespace(id=4, name="kilo", key_prefix="alpha_router_Maj")
    exported = log_row_to_export(
        row,
        tz_mode="utc",
        provider="openai",
        router_key=None,
        user_key=user_key,
    )
    assert exported["User"] == "majid · kilo (Personal API Key)"


def test_log_row_personal_api_key_identity_is_user():
    from app.api.logs import _log_row

    row = SimpleNamespace(
        id=3,
        request_time=datetime(2026, 8, 17, 12, 0, 0),
        username="majid",
        source="user_key",
        client_app="Kilo Code",
        alpha_router_api_key_id=None,
        user_api_key_id=4,
        model_id="gpt-4o-mini",
        prompt_tokens=1,
        completion_tokens=2,
        cached_tokens=0,
        total_cost_usd=0.1,
        provider_cost_usd=None,
        calculated_cost_usd=0.1,
        cost_source="provider_catalog",
        cost_confidence="exact",
        has_unpriced_usage=False,
        response_time_ms=10,
        success=True,
        source_ip="10.0.0.1",
        prompt_language="en",
        error_message=None,
        reconciled_at=None,
        usage_operation_id=None,
    )
    user_key = SimpleNamespace(id=4, name="kilo", key_prefix="alpha_router_Maj")
    payload = _log_row(row, provider="openai", user_key=user_key)
    assert payload["identity_type"] == "user"
    assert payload["username"] == "majid"
    assert payload["api_key_name"] == "kilo"
    assert payload["api_key_kind"] == "personal"


def test_single_log_detail_export_includes_events_and_line_items():
    log_row = SimpleNamespace(
        id=9,
        request_time=datetime(2026, 8, 7, 15, 30, 0),
        username="carol",
        source="gateway",
        client_app="SDK",
        alpha_router_api_key_id=None,
        model_id="gpt-4o-mini",
        prompt_tokens=100,
        completion_tokens=50,
        cached_tokens=0,
        total_cost_usd=0.2,
        provider_cost_usd=None,
        calculated_cost_usd=0.2,
        cost_source="provider_catalog",
        cost_confidence="calculated",
        has_unpriced_usage=False,
        response_time_ms=40,
        success=True,
        source_ip="10.0.0.2",
        prompt_language="en",
    )
    operation = SimpleNamespace(
        id="op-1",
        operation_type="chat",
        status="succeeded",
        total_cost_usd=0.2,
        provider_cost_usd=None,
        calculated_cost_usd=0.2,
    )
    event = SimpleNamespace(
        id="evt-1",
        operation_id="op-1",
        attempt_index=0,
        provider_type="openai",
        service_type="chat",
        operation_name="chat.completions",
        model_id="gpt-4o-mini",
        status="succeeded",
        upstream_request_id="resp_123",
        prompt_tokens=100,
        completion_tokens=50,
        cached_tokens=0,
        reasoning_tokens=0,
        final_cost_usd=0.2,
        provider_cost_usd=None,
        calculated_cost_usd=0.2,
        cost_source="provider_catalog",
        cost_confidence="calculated",
    )
    line = SimpleNamespace(
        category="input_tokens",
        quantity=100,
        unit="token",
        unit_price_usd=0.001,
        cost_usd=0.1,
        pricing_source="provider_catalog",
    )
    rows = request_log_detail_to_export_rows(
        log_row,
        tz_mode="utc",
        provider="openai",
        router_key=None,
        operation=operation,
        events=[event],
        lines_by_event={"evt-1": [line]},
    )
    assert [r["Row Type"] for r in rows] == ["request", "event", "line_item"]
    assert rows[1]["Upstream Request Id"] == "resp_123"
    assert rows[2]["Line Category"] == "input_tokens"
    csv_text = detail_rows_to_csv_bytes(rows).decode("utf-8-sig")
    assert csv_text.splitlines()[0] == ",".join(DETAIL_LOG_COLUMNS)
    assert "line_item" in csv_text
