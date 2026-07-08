"""HTTP client for the Windows LDAP bridge (signed LDAP from Linux/Docker)."""

from __future__ import annotations

from typing import Any

import httpx

from app.config import get_settings


class LdapBridgeError(RuntimeError):
    pass


def ldap_bridge_enabled() -> bool:
    return bool((get_settings().ldap_bridge_url or "").strip())


def _bridge_base() -> str:
    return (get_settings().ldap_bridge_url or "").strip().rstrip("/")


def _headers() -> dict[str, str]:
    token = (get_settings().ldap_bridge_token or "").strip()
    if not token:
        return {}
    return {"Authorization": f"Bearer {token}"}


def _post(path: str, payload: dict[str, Any], *, timeout: float = 120.0) -> Any:
    url = f"{_bridge_base()}{path}"
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(url, json=payload, headers=_headers())
    except httpx.RequestError as exc:
        raise LdapBridgeError(
            f"Could not reach LDAP bridge at {url}. Start scripts/start-ldap-bridge.ps1 on the Windows host."
        ) from exc
    if resp.status_code >= 400:
        detail = resp.text.strip() or resp.reason_phrase
        raise LdapBridgeError(f"LDAP bridge error ({resp.status_code}): {detail}")
    return resp.json()


def bridge_probe_directory(host: str, port: int, bind_username: str, password: str) -> dict[str, Any]:
    return _post(
        "/v1/probe",
        {
            "host": host,
            "port": int(port or 389),
            "bind_username": bind_username,
            "bind_password": password,
        },
    )


def bridge_test_connection(cfg: dict) -> dict[str, Any]:
    return _post("/v1/test", {"config": cfg})


def bridge_fetch_users(cfg: dict) -> list[dict[str, Any]]:
    return _post("/v1/users", {"config": cfg})


def bridge_fetch_groups(cfg: dict) -> list[dict[str, Any]]:
    return _post("/v1/groups", {"config": cfg})


def bridge_authenticate(username: str, password: str, cfg: dict) -> dict[str, Any] | None:
    result = _post(
        "/v1/authenticate",
        {"username": username, "password": password, "config": cfg},
        timeout=30.0,
    )
    if result is None:
        return None
    return result if isinstance(result, dict) else None
