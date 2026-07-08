"""Human-readable labels for stored enum-like codes."""

APP_SOURCE_LABELS: dict[str, str] = {
    "openwebui": "Open WebUI",
    "nitro_key": "NITRO API Key",
    "billi_key": "NITRO API Key",  # legacy log rows
    "user_key": "User API Key",
    "nitro_chat": "NITRO Chat",
    "billi_chat": "NITRO Chat",  # legacy log rows
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
