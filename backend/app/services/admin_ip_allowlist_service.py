"""Admin IP allowlist storage, validation, and process-local cache."""

from __future__ import annotations

import ipaddress
import time
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.security import AdminIpAllowlistEntry
from app.models.system import SystemSetting
from app.services.client_ip import canonical_ip, ip_in_networks, ip_is_loopback, parse_cidrs

RestrictionMode = Literal["off", "monitor", "enforce"]

KEY_MODE = "admin_ip_restriction_mode"
KEY_ALLOW_LOOPBACK = "admin_ip_allow_loopback"
MAX_ENTRIES = 200
CACHE_TTL_SECONDS = 15.0
WILDCARD_NETWORKS = frozenset(
    {
        ipaddress.ip_network("0.0.0.0/0"),
        ipaddress.ip_network("::/0"),
    }
)

_cache: tuple[float, RestrictionState] | None = None


class AllowlistError(ValueError):
    pass


@dataclass(frozen=True)
class RestrictionState:
    mode: RestrictionMode
    allow_loopback: bool
    entries: tuple[dict[str, Any], ...]

    @property
    def enabled_cidrs(self) -> tuple[str, ...]:
        return tuple(item["cidr"] for item in self.entries if item.get("enabled"))


def invalidate_restriction_cache() -> None:
    global _cache
    _cache = None


def peek_restriction_state(*, allow_stale: bool = False) -> RestrictionState | None:
    if _cache is None:
        return None
    cached_at, state = _cache
    if not allow_stale and time.monotonic() - cached_at > CACHE_TTL_SECONDS:
        return None
    return state


def normalize_cidr(raw: str) -> str:
    token = (raw or "").strip()
    if not token:
        raise AllowlistError("Enter an IP address or CIDR range.")
    if "/" not in token:
        addr = canonical_ip(token)
        if addr is None:
            raise AllowlistError("Use a valid IPv4 or IPv6 address.")
        token = f"{addr}/32" if addr.version == 4 else f"{addr}/128"
    try:
        network = ipaddress.ip_network(token, strict=False)
    except ValueError as exc:
        raise AllowlistError("Use a valid IPv4/IPv6 address or CIDR range.") from exc
    if network in WILDCARD_NETWORKS:
        raise AllowlistError("The entire Internet (0.0.0.0/0 or ::/0) cannot be allowlisted.")
    return str(network)


def ip_matches_allowlist(
    client_ip: str | None,
    entries: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    *,
    allow_loopback: bool,
) -> bool:
    if allow_loopback and ip_is_loopback(client_ip):
        return True
    addr = canonical_ip(client_ip)
    if addr is None:
        return False
    networks = []
    for item in entries:
        if not item.get("enabled", True):
            continue
        networks.extend(parse_cidrs(str(item.get("cidr") or "")))
    return ip_in_networks(addr, networks)


def _mode_from_value(raw: str | None) -> RestrictionMode:
    value = (raw or "off").strip().lower()
    if value in {"off", "monitor", "enforce"}:
        return value  # type: ignore[return-value]
    return "off"


def _serialize_entry(row: AdminIpAllowlistEntry) -> dict[str, Any]:
    return {
        "id": row.id,
        "cidr": row.cidr,
        "label": row.label or "",
        "enabled": bool(row.enabled),
        "created_at": row.created_at.isoformat() + "Z" if row.created_at else None,
    }


async def _setting(db: AsyncSession, key: str) -> str | None:
    row = await db.get(SystemSetting, key)
    return None if row is None else row.value


async def _set_setting(db: AsyncSession, key: str, value: str) -> None:
    row = await db.get(SystemSetting, key)
    if row:
        row.value = value
    else:
        db.add(SystemSetting(key=key, value=value))


async def list_entries(db: AsyncSession) -> list[dict[str, Any]]:
    rows = (await db.execute(select(AdminIpAllowlistEntry).order_by(AdminIpAllowlistEntry.id.asc()))).scalars().all()
    return [_serialize_entry(row) for row in rows]


async def get_restriction_state(db: AsyncSession) -> RestrictionState:
    global _cache
    fresh = peek_restriction_state()
    if fresh is not None:
        return fresh
    mode = _mode_from_value(await _setting(db, KEY_MODE))
    loopback_raw = (await _setting(db, KEY_ALLOW_LOOPBACK) or "true").strip().lower()
    allow_loopback = loopback_raw not in {"0", "false", "no"}
    entries = tuple(await list_entries(db))
    state = RestrictionState(mode=mode, allow_loopback=allow_loopback, entries=entries)
    _cache = (time.monotonic(), state)
    return state


async def add_entry(
    db: AsyncSession,
    *,
    cidr: str,
    label: str = "",
    created_by_user_id: int | None,
) -> dict[str, Any]:
    normalized = normalize_cidr(cidr)
    existing = await list_entries(db)
    if len(existing) >= MAX_ENTRIES:
        raise AllowlistError(f"Allowlist is limited to {MAX_ENTRIES} entries.")
    if any(item["cidr"] == normalized for item in existing):
        raise AllowlistError("That IP or CIDR is already on the allowlist.")
    row = AdminIpAllowlistEntry(
        cidr=normalized,
        label=(label or "").strip()[:128] or None,
        enabled=True,
        created_by_user_id=created_by_user_id,
    )
    db.add(row)
    await db.flush()
    invalidate_restriction_cache()
    return _serialize_entry(row)


async def _reject_if_would_lock_out(
    db: AsyncSession,
    *,
    client_ip: str | None,
    remaining_entries: list[dict[str, Any]] | tuple[dict[str, Any], ...],
) -> None:
    state = await get_restriction_state(db)
    if state.mode != "enforce":
        return
    if ip_matches_allowlist(client_ip, remaining_entries, allow_loopback=state.allow_loopback):
        return
    shown = client_ip or "unknown"
    raise AllowlistError(f"Cannot change the allowlist because it would lock out your current IP ({shown}).")


async def update_entry(
    db: AsyncSession,
    entry_id: int,
    *,
    label: str | None = None,
    enabled: bool | None = None,
    client_ip: str | None = None,
) -> dict[str, Any]:
    row = await db.get(AdminIpAllowlistEntry, entry_id)
    if row is None:
        raise AllowlistError("Allowlist entry not found.")
    if enabled is False:
        state = await get_restriction_state(db)
        remaining = [{**item, "enabled": False} if item["id"] == entry_id else item for item in state.entries]
        await _reject_if_would_lock_out(db, client_ip=client_ip, remaining_entries=remaining)
    if label is not None:
        row.label = label.strip()[:128] or None
    if enabled is not None:
        row.enabled = bool(enabled)
    await db.flush()
    invalidate_restriction_cache()
    return _serialize_entry(row)


async def delete_entry(
    db: AsyncSession,
    entry_id: int,
    *,
    client_ip: str | None = None,
) -> None:
    row = await db.get(AdminIpAllowlistEntry, entry_id)
    if row is None:
        raise AllowlistError("Allowlist entry not found.")
    state = await get_restriction_state(db)
    remaining = [item for item in state.entries if item["id"] != entry_id]
    await _reject_if_would_lock_out(db, client_ip=client_ip, remaining_entries=remaining)
    await db.delete(row)
    await db.flush()
    invalidate_restriction_cache()


async def set_restriction_mode(
    db: AsyncSession,
    mode: RestrictionMode,
    *,
    client_ip: str | None,
    allow_loopback: bool | None = None,
) -> RestrictionState:
    if mode not in {"off", "monitor", "enforce"}:
        raise AllowlistError("Mode must be off, monitor, or enforce.")
    if allow_loopback is not None:
        await _set_setting(db, KEY_ALLOW_LOOPBACK, "true" if allow_loopback else "false")
    invalidate_restriction_cache()
    state = await get_restriction_state(db)
    if mode == "enforce" and not ip_matches_allowlist(
        client_ip,
        state.entries,
        allow_loopback=state.allow_loopback,
    ):
        shown = client_ip or "unknown"
        raise AllowlistError(f"Cannot enforce the allowlist because your current IP ({shown}) is not listed.")
    await _set_setting(db, KEY_MODE, mode)
    invalidate_restriction_cache()
    return await get_restriction_state(db)
