"""Human-readable labels for stored enum-like codes."""

from app.branding import CHAT_CLIENT_APP, PRODUCT_NAME

APP_SOURCE_LABELS: dict[str, str] = {
    "openwebui": "Open WebUI",
    "alpha_router_key": f"{PRODUCT_NAME} API Key",
    "user_key": "User API Key",
    "alpha_router_chat": CHAT_CLIENT_APP,
    "gateway": "Platform API",
}


def format_app_source(source: str | None) -> str:
    """Map request log `source` codes to display names for the App column."""
    if not source or not str(source).strip():
        return "Unknown"
    key = str(source).strip().lower()
    if key in APP_SOURCE_LABELS:
        return APP_SOURCE_LABELS[key]
    return str(source).replace("_", " ").strip().title()
