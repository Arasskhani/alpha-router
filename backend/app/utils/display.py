"""Human-readable labels for stored enum-like codes."""

APP_SOURCE_LABELS: dict[str, str] = {
    "openwebui": "Open WebUI",
    "alpha_router_key": "Alpha Router API Key",
    "alpha_router_key": "Alpha Router API Key",  # legacy log rows
    "user_key": "User API Key",
    "alpha_router_chat": "Alpha Router Chat",
    "alpha_router_chat": "Alpha Router Chat",  # legacy log rows
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
