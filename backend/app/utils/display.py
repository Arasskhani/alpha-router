"""Human-readable labels for stored enum-like codes."""

from app.branding import CHAT_CLIENT_APP, EXTENSION_CLIENT_APP, PRODUCT_NAME

#: ``request_logs.source`` for automatic memory extraction. Activity, the
#: app filter and the reports all group on this field, so the constant and
#: its label belong together rather than in the service that writes it.
MEMORY_USAGE_SOURCE = "system_memory"

APP_SOURCE_LABELS: dict[str, str] = {
    "openwebui": "Open WebUI",
    "alpha_router_key": f"{PRODUCT_NAME} API Key",
    "user_key": "User API Key",
    "alpha_router_chat": CHAT_CLIENT_APP,
    "gateway": "Platform API",
    # Without this the rows would read "System Memory".
    MEMORY_USAGE_SOURCE: "Memory",
}


def format_app_source(source: str | None) -> str:
    """Map request log `source` codes to display names for the App column."""
    if not source or not str(source).strip():
        return "Unknown"
    key = str(source).strip().lower()
    if key in APP_SOURCE_LABELS:
        return APP_SOURCE_LABELS[key]
    return str(source).replace("_", " ").strip().title()


def request_log_app(source: str | None, client_app: str | None) -> str:
    """The App column of a request log row.

    Chat turns (and their helper calls, "… (helper:title)") read as the chat
    itself, except the browser extension's, which say so; any other client is
    named as it announced itself.
    """
    client = (client_app or "").strip()
    if (source or "").strip().lower() == "alpha_router_chat":
        return EXTENSION_CLIENT_APP if client.startswith(EXTENSION_CLIENT_APP) else format_app_source(source)
    return client or format_app_source(source)
