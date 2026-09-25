"""API log row identity helpers for personal vs gateway keys."""

from types import SimpleNamespace

from app.api.logs import _log_row


def _base_log(**overrides):
    values = {
        "id": 1,
        "request_time": None,
        "username": "majid",
        "model_id": "openrouter/qwen/qwen-plus",
        "prompt_language": "en",
        "prompt_tokens": 10,
        "completion_tokens": 5,
        "cached_tokens": 0,
        "total_cost_usd": 0.01,
        "provider_cost_usd": None,
        "calculated_cost_usd": None,
        "cost_source": "unknown",
        "cost_confidence": "unknown",
        "has_unpriced_usage": False,
        "usage_operation_id": None,
        "reconciled_at": None,
        "response_time_ms": 100.0,
        "source_ip": "127.0.0.1",
        "source": "user_key",
        "client_app": "Kilo Code",
        "success": True,
        "error_message": None,
        "alpha_router_api_key_id": None,
        "user_api_key_id": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_log_row_marks_personal_key_from_source_without_key_join():
    row = _log_row(_base_log(source="user_key", user_api_key_id=None))
    assert row["api_key_kind"] == "personal"
    assert row["username"] == "majid"


def test_log_row_marks_personal_key_from_user_api_key_id():
    row = _log_row(_base_log(source="openwebui", user_api_key_id=42))
    assert row["api_key_kind"] == "personal"
    assert row["user_api_key_id"] == 42


def test_log_row_gateway_key_keeps_gateway_kind():
    router_key = SimpleNamespace(id=9, name="Kilo", key_prefix="ar_kil")
    row = _log_row(
        _base_log(
            source="alpha_router_key",
            username="Kilo",
            alpha_router_api_key_id=9,
            user_api_key_id=None,
        ),
        router_key=router_key,
    )
    assert row["api_key_kind"] == "gateway"
    assert row["identity_type"] == "api_key"


def test_the_app_column_names_the_browser_extension():
    """Chat turns read as the chat, helper calls included - except the extension's, which say so."""
    assert _log_row(_base_log(source="alpha_router_chat", client_app="Alpharouter Chat"))["app"] == "Alpharouter Chat"
    assert _log_row(_base_log(source="alpha_router_chat", client_app="Alpharouter Chat (helper:title)"))["app"] == (
        "Alpharouter Chat"
    )
    assert _log_row(_base_log(source="alpha_router_chat", client_app="Alpharouter Extension"))["app"] == (
        "Alpharouter Extension"
    )
    assert _log_row(_base_log(source="alpha_router_chat", client_app="Alpharouter Extension (helper:title)"))[
        "app"
    ] == ("Alpharouter Extension")
    assert _log_row(_base_log(source="user_key", client_app="Kilo Code"))["app"] == "Kilo Code"


def test_the_export_names_the_browser_extension_too():
    from app.services.log_export_service import _format_app

    assert (
        _format_app(_base_log(source="alpha_router_chat", client_app="Alpharouter Extension"))
        == "Alpharouter Extension"
    )
    assert _format_app(_base_log(source="alpha_router_chat", client_app=None)) == "Alpharouter Chat"
