"""Server-local timezone for scheduled cleanup jobs (APScheduler cron)."""

from __future__ import annotations

import logging
import os
import zoneinfo
from datetime import datetime

logger = logging.getLogger(__name__)


def get_server_timezone():
    """Timezone for cron triggers: ``TZ`` env when set, else OS local timezone."""
    tz_name = (os.environ.get("TZ") or "").strip()
    if tz_name:
        try:
            return zoneinfo.ZoneInfo(tz_name)
        except zoneinfo.ZoneInfoNotFoundError:
            logger.warning("Invalid TZ=%r; falling back to system local timezone", tz_name)
    return datetime.now().astimezone().tzinfo


def server_timezone_label() -> str:
    tz = get_server_timezone()
    if isinstance(tz, zoneinfo.ZoneInfo):
        return tz.key
    name = tz.tzname(None) if tz else None
    return name or "local"
