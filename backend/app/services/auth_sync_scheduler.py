"""Scheduled LDAP directory sync."""

from __future__ import annotations

import logging

from app.database import AsyncSessionLocal
from app.services.auth_config import get_provider_config
from app.services.ldap_sync import sync_ldap_directory
from app.services.scheduler import scheduler

logger = logging.getLogger(__name__)


def _schedule_fields(cfg: dict) -> tuple[bool, int, int]:
    enabled = bool(cfg.get("sync_schedule_enabled"))
    hour = max(0, min(23, int(cfg.get("sync_schedule_hour", 3))))
    minute = max(0, min(59, int(cfg.get("sync_schedule_minute", 0))))
    return enabled, hour, minute


async def job_ldap_directory_sync() -> None:
    async with AsyncSessionLocal() as db:
        cfg = await get_provider_config(db, "ldap")
        if not cfg.get("enabled"):
            return
        try:
            result = await sync_ldap_directory(db, cfg)
            logger.info("Scheduled LDAP sync finished: %s", result)
        except Exception:
            logger.exception("Scheduled LDAP sync failed")


async def refresh_auth_sync_schedules() -> None:
    async with AsyncSessionLocal() as db:
        ldap_cfg = await get_provider_config(db, "ldap")

    for job_id in ("ldap_directory_sync", "keycloak_directory_sync"):
        if scheduler.get_job(job_id):
            scheduler.remove_job(job_id)

    ldap_enabled, ldap_hour, ldap_minute = _schedule_fields(ldap_cfg)
    if ldap_cfg.get("enabled") and ldap_enabled:
        scheduler.add_job(
            job_ldap_directory_sync,
            "cron",
            hour=ldap_hour,
            minute=ldap_minute,
            id="ldap_directory_sync",
        )

    # Only the elected leader runs jobs; on other workers the entries stay
    # pending and become live if this worker is ever elected.
    from app.services.scheduler_leader import is_leader

    if is_leader() and not scheduler.running and scheduler.get_jobs():
        scheduler.start()
