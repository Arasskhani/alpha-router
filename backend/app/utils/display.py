"""Human-readable labels for stored enum-like codes."""

from app.branding import CHAT_CLIENT_APP, PRODUCT_NAME

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
