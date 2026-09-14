"""Characterization tests for project-owned naming contracts.

These assertions intentionally lock the current phase's values. Each coordinated
rename phase updates the relevant assertion alongside its production contract.
"""

import asyncio
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine

from app.branding import (
    API_KEY_PREFIX,
    OIDC_STATE_COOKIE_NAME,
    OUTBOUND_USER_AGENT,
    PRODUCT_NAME,
    PRODUCT_NAME_MARKED,
    REPLACE_MESSAGES_HEADER,
    TRADEMARK_OWNER,
    TRADEMARK_SYMBOL,
)
from app.config import Settings
from app.core.security import generate_api_key_for_user
from app.database import Base
from app.main import app, health_payload
from app.models.api_key import AlphaRouterApiKey, AlphaRouterApiKeyAuditLog
from app.models.logging import RequestLog
from app.sandbox_broker import SANDBOX_IMAGE
from app.sandbox_broker import app as sandbox_broker_app
from app.services import chat_feedback_service, chat_title_service, user_chat_storage_service
from app.services.budget_reservation_service import SUBJECT_ALPHA_ROUTER_KEY
from app.services.chat_import_export import CHAT_EXPORT_FORMAT, detect_import_format
from app.services.chat_markers import AUDIO_MESSAGE_PREFIX
from app.services.code_interpreter_service import ATTACH_PREFIX
from app.services.db_monitor_service import TABLE_LABELS
from app.services.openrouter_image_service import build_openrouter_headers
from app.services.reports_catalog import REPORT_CATALOG
from app.services.totp_service import provisioning_uri
from app.utils.app_attribution import detect_client_app
from app.utils.display import format_app_source


def _default(field_name: str):
    return Settings.model_fields[field_name].default


def test_application_identity_contracts():
    assert PRODUCT_NAME == "Alpharouter"
    assert TRADEMARK_SYMBOL == "™"
    assert PRODUCT_NAME_MARKED == "Alpharouter™"
    assert TRADEMARK_OWNER == "Majid Arasskhani"
    assert _default("app_name") == "Alpharouter"
    assert app.title == "Alpharouter Organizational AI Platform"
    assert sandbox_broker_app.title == "Alpharouter Sandbox Broker"
    assert health_payload() == {"status": "ok", "service": "alpha-router"}
    assert format_app_source("alpha_router_key") == "Alpharouter API Key"
    assert format_app_source("alpha_router_chat") == "Alpharouter Chat"


def test_infrastructure_identity_contracts():
    assert _default("database_url") == ("postgresql+asyncpg://alpha_router:changeme@postgres:5432/alpha_router")
    assert _default("s3_access_key") == "alpha_router"
    assert _default("s3_bucket") == "alpha-router-media"
    assert SANDBOX_IMAGE == "alpha-router-sandbox:latest"


def test_auth_and_api_key_naming_contracts():
    assert _default("session_cookie_name") == "alpha_router_session"
    assert _default("csrf_cookie_name") == "alpha_router_csrf"
    assert _default("gateway_master_key") == "sk-alpha-router-master"
    assert OIDC_STATE_COOKIE_NAME == "alpha_router_oidc_state"
    assert REPLACE_MESSAGES_HEADER == "X-Alpha-Router-Replace-Messages"

    raw, prefix, _ = generate_api_key_for_user("branding.test")
    assert API_KEY_PREFIX == "alpha_router_"
    assert raw.startswith("alpha_router_branding.test_")
    assert prefix == raw[:16]


def test_totp_and_provider_attribution_contracts():
    uri = provisioning_uri("JBSWY3DPEHPK3PXP", "alice")
    assert parse_qs(urlparse(uri).query)["issuer"] == ["Alpharouter"]

    headers = build_openrouter_headers("secret", referer="https://alpha-router.local")
    assert headers["X-Title"] == "Alpharouter"
    assert OUTBOUND_USER_AGENT == "AlphaRouter/1.0 (+https://alpha-router.local)"

    request = SimpleNamespace(headers={"referer": "http://localhost:8080/admin/chat"})
    assert detect_client_app(request) == "Alpharouter Chat"


def test_database_naming_contracts():
    assert AlphaRouterApiKey.__tablename__ == "alpha_router_api_keys"
    assert AlphaRouterApiKeyAuditLog.__tablename__ == "alpha_router_api_key_audit_logs"
    assert "alpha_router_api_key_id" in AlphaRouterApiKeyAuditLog.__table__.c
    assert "alpha_router_api_key_id" in RequestLog.__table__.c

    audit_fk = next(iter(AlphaRouterApiKeyAuditLog.__table__.c.alpha_router_api_key_id.foreign_keys))
    request_fk = next(iter(RequestLog.__table__.c.alpha_router_api_key_id.foreign_keys))
    assert audit_fk.target_fullname == "alpha_router_api_keys.id"
    assert request_fk.target_fullname == "alpha_router_api_keys.id"
    assert SUBJECT_ALPHA_ROUTER_KEY == "alpha_router_key"

    monitored_tables = {table for table, _ in TABLE_LABELS}
    assert "alpha_router_api_keys" in monitored_tables
    assert "alpha_router_api_key_audit_logs" in monitored_tables
    assert "alpha_router_api_key_connections" in monitored_tables
    assert "alpha_router_api_key_models" in monitored_tables

    report_ids = {report["id"] for report in REPORT_CATALOG}
    assert "alpha_router_api_key_usage" in report_ids
    assert "alpha_router_api_keys_near_credit_limit" in report_ids
    assert "agent_usage" in report_ids


async def _test_fresh_database_schema_contracts() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

            def snapshot(sync_conn):
                inspector = inspect(sync_conn)
                tables = set(inspector.get_table_names())
                request_columns = {column["name"] for column in inspector.get_columns("request_logs")}
                audit_columns = {column["name"] for column in inspector.get_columns("alpha_router_api_key_audit_logs")}
                usage_event_columns = {column["name"] for column in inspector.get_columns("usage_events")}
                return tables, request_columns, audit_columns, usage_event_columns

            (
                tables,
                request_columns,
                audit_columns,
                usage_event_columns,
            ) = await conn.run_sync(snapshot)
    finally:
        await engine.dispose()

    assert "alpha_router_api_keys" in tables
    assert "alpha_router_api_key_audit_logs" in tables
    assert "alpha_router_api_key_connections" in tables
    assert "alpha_router_api_key_models" in tables
    assert "pricing_snapshots" in tables
    assert "usage_operations" in tables
    assert "usage_events" in tables
    assert "cost_line_items" in tables
    assert "cost_ledger_entries" in tables
    assert "reconciliation_runs" in tables
    assert "alpha_router_api_key_id" in request_columns
    assert "usage_operation_id" in request_columns
    assert "cost_source" in request_columns
    assert "cost_confidence" in request_columns
    assert "alpha_router_api_key_id" in audit_columns
    assert "final_cost_usd" in usage_event_columns
    assert "reconciliation_attempts" in usage_event_columns


def test_fresh_database_schema_contracts() -> None:
    asyncio.run(_test_fresh_database_schema_contracts())


def test_chat_wire_and_export_contracts():
    assert user_chat_storage_service.IMAGE_MESSAGE_PREFIX == "__ALPHA_ROUTER_IMAGE_JSON__:"
    assert user_chat_storage_service.IMAGE_PENDING_MARKER == "__ALPHA_ROUTER_IMAGE_PENDING__"
    assert user_chat_storage_service.ATTACHMENT_MESSAGE_PREFIX == "__ALPHA_ROUTER_ATTACH_JSON__:"
    assert AUDIO_MESSAGE_PREFIX == "__ALPHA_ROUTER_AUDIO_JSON__:"
    assert chat_title_service._IMAGE_PREFIX == "__ALPHA_ROUTER_IMAGE_JSON__:"
    assert chat_title_service._IMAGE_PENDING == "__ALPHA_ROUTER_IMAGE_PENDING__"
    assert chat_feedback_service.IMAGE_MESSAGE_PREFIX == "__ALPHA_ROUTER_IMAGE_JSON__:"
    assert chat_feedback_service.IMAGE_PENDING_MARKER == "__ALPHA_ROUTER_IMAGE_PENDING__"
    assert ATTACH_PREFIX == "__ALPHA_ROUTER_ATTACH_JSON__:"
    assert detect_import_format({"format": CHAT_EXPORT_FORMAT, "version": 1, "sessions": []}) == "alpha-router-chats"


def test_chat_title_marker_parsing_uses_current_contracts():
    assert (
        chat_title_service._normalize_content_for_title('__ALPHA_ROUTER_IMAGE_JSON__:{"prompt":"Draw a fox"}')
        == "Draw a fox"
    )
    assert (
        chat_title_service._normalize_content_for_title('__ALPHA_ROUTER_ATTACH_JSON__:{"userText":"Review this"}')
        == "Review this"
    )
    assert (
        chat_title_service._normalize_content_for_title('__ALPHA_ROUTER_AUDIO_JSON__:{"transcript":"Voice note"}')
        == "Voice note"
    )
