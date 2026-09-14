"""Materialize TLS state for the host-network edge proxy and generate nginx config."""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.security import TlsCertificate
from app.models.system import SystemSetting
from app.services.client_ip import local_gateway_networks
from app.services.tls_certificate_service import (
    TlsCertificateError,
    decrypt_private_key,
    get_certificate,
)

HttpMode = Literal["redirect", "loopback_only"]

LOGGER = logging.getLogger("app.services.tls_edge")

KEY_HTTPS_PORT = "tls_https_port"
KEY_HTTP_MODE = "tls_http_mode"
KEY_HSTS = "tls_hsts_enabled"
KEY_GENERATION = "tls_generation"
RESERVED_PORTS = frozenset({8080, 8081, 5432, 6432, 6379, 6333, 6334, 8333, 3310, 9333, 23646})
# Fallback only when transfer limits are unavailable during render.
DEFAULT_MAX_BODY_MB = 1024
_NGINX_BODY_RE = re.compile(r"client_max_body_size\s+(\d+)m\s*;", re.IGNORECASE)


def tls_state_dir() -> Path:
    raw = (getattr(get_settings(), "tls_state_dir", "") or "").strip()
    return Path(raw) if raw else Path("/app/tls")


def atomic_write(path: Path, data: bytes | str, *, mode: int = 0o644) -> None:
    """Write via a temp file created with its final mode, then rename.

    The mode is applied by os.open so a private key is never briefly readable
    by other users on the shared volume.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = data.encode("utf-8") if isinstance(data, str) else data
    tmp = path.with_name(path.name + ".tmp")
    if tmp.exists():
        tmp.unlink()
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    os.chmod(tmp, mode)
    os.replace(tmp, path)


def validate_https_port(port: int) -> int:
    if not isinstance(port, int) or port < 1 or port > 65535:
        raise TlsCertificateError("HTTPS port must be between 1 and 65535.")
    if port in RESERVED_PORTS:
        raise TlsCertificateError(f"Port {port} is reserved by Alpharouter services.")
    return port


def render_nginx_config(
    *,
    https_port: int,
    http_mode: HttpMode,
    hsts_enabled: bool,
    has_chain: bool,
    upstream: str = "127.0.0.1:8080",
    max_body_mb: int = DEFAULT_MAX_BODY_MB,
    json_body_mb: int | None = None,
) -> str:
    """Render the edge config.

    ``max_body_mb`` is the upload ceiling and stays on the http block (the
    value read_nginx_client_max_body_mb() reads back). Ordinary JSON routes get
    ``json_body_mb`` (defaults to MAX_JSON_BODY_BYTES) in ``location /``; the
    large-body routes listed in request_body_limit_service inherit the upload
    ceiling through a regex location, mirroring the app middleware tiers.
    """
    from app.services.request_body_limit_service import LARGE_BODY_PATH_PREFIXES

    if json_body_mb is None:
        json_body_mb = default_json_body_mb()
    json_body_mb = max(1, min(int(json_body_mb), max(1, int(max_body_mb))))
    large_paths = "|".join(re.escape(prefix.lstrip("/")) for prefix in LARGE_BODY_PATH_PREFIXES)
    proxy_directives = f"""            proxy_pass http://{upstream};
            proxy_http_version 1.1;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto https;
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection $connection_upgrade;
            proxy_buffering off;
            proxy_read_timeout 3600s;
            proxy_send_timeout 3600s;"""
    hsts = ""
    if hsts_enabled:
        hsts = '    add_header Strict-Transport-Security "max-age=31536000" always;\n'
    stapling = ""
    if has_chain:
        stapling = (
            "    ssl_trusted_certificate /etc/alpha-router/tls/chain.pem;\n"
            "    ssl_stapling on;\n"
            "    ssl_stapling_verify on;\n"
        )
    redirect_block = ""
    if http_mode == "redirect":
        target = "$host" if https_port == 443 else f"$host:{https_port}"
        redirect_block = f"""
server {{
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name _;
    return 301 https://{target}$request_uri;
}}
"""
    return f"""worker_processes auto;
error_log /var/log/nginx/error.log warn;
pid /run/nginx.pid;
events {{
    worker_connections 1024;
}}
http {{
    include /etc/nginx/mime.types;
    default_type application/octet-stream;
    sendfile on;
    # No version banner; the access log is off (it would record every chat
    # URL incl. session ids and query strings on the tmpfs; the app has its
    # own structured request log with the right redactions).
    server_tokens off;
    access_log off;
    client_max_body_size {max(1, int(max_body_mb))}m;
    map $http_upgrade $connection_upgrade {{
        default upgrade;
        '' close;
    }}
    {redirect_block}
    server {{
        listen {https_port} ssl;
        listen [::]:{https_port} ssl;
        http2 on;
        server_name _;
        ssl_certificate /etc/alpha-router/tls/fullchain.pem;
        ssl_certificate_key /etc/alpha-router/tls/key.pem;
        ssl_protocols TLSv1.2 TLSv1.3;
        # Mozilla "intermediate" TLS 1.2 suites (TLS 1.3 suites are fixed).
        ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305:DHE-RSA-AES128-GCM-SHA256:DHE-RSA-AES256-GCM-SHA384;
        ssl_prefer_server_ciphers off;
        ssl_session_timeout 1d;
        ssl_session_cache shared:SSL:10m;
        # Session tickets would need a rotated key to keep forward secrecy;
        # the shared cache above is enough for a single edge.
        ssl_session_tickets off;
{stapling}{hsts}
        # Ordinary JSON: small ceiling (mirrors MAX_JSON_BODY_BYTES).
        location / {{
            client_max_body_size {json_body_mb}m;
{proxy_directives}
        }}
        # Uploads and inline-image chat bodies: inherit the http-level ceiling.
        location ~ ^/({large_paths}) {{
{proxy_directives}
        }}
    }}
}}
"""


def read_desired_state() -> dict[str, Any]:
    path = tls_state_dir() / "desired-state.json"
    if not path.is_file():
        return {"enabled": False, "generation": 0}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"enabled": False, "generation": 0}


def read_apply_status() -> dict[str, Any] | None:
    path = tls_state_dir() / "apply-status.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def write_desired_state(payload: dict[str, Any]) -> None:
    atomic_write(tls_state_dir() / "desired-state.json", json.dumps(payload, indent=2) + "\n")


def _join_pem(leaf: str, chain: str | None) -> str:
    parts = [leaf.strip(), (chain or "").strip()]
    return "".join(part + "\n" for part in parts if part)


def materialize_certificate_files(cert_pem: str, key_pem: str, chain_pem: str | None) -> None:
    root = tls_state_dir()
    leaf = cert_pem.strip() + "\n"
    chain = (chain_pem or "").strip()
    atomic_write(root / "cert.pem", leaf, mode=0o644)
    atomic_write(root / "fullchain.pem", _join_pem(leaf, chain), mode=0o644)
    atomic_write(root / "key.pem", key_pem, mode=0o600)
    if chain:
        atomic_write(root / "chain.pem", chain + "\n", mode=0o644)
    else:
        chain_path = root / "chain.pem"
        if chain_path.exists():
            chain_path.unlink()


MATERIALIZED_TLS_FILES = ("cert.pem", "fullchain.pem", "key.pem", "chain.pem")


def wipe_materialized_certificate_files() -> None:
    root = tls_state_dir()
    for name in MATERIALIZED_TLS_FILES:
        (root / name).unlink(missing_ok=True)


async def _next_generation(db: AsyncSession) -> int:
    row = await db.get(SystemSetting, KEY_GENERATION)
    current = int(row.value or 0) if row and row.value else 0
    nxt = current + 1
    if row:
        row.value = str(nxt)
    else:
        db.add(SystemSetting(key=KEY_GENERATION, value=str(nxt)))
    await db.flush()
    return nxt


async def _set_setting(db: AsyncSession, key: str, value: str) -> None:
    row = await db.get(SystemSetting, key)
    if row:
        row.value = value
    else:
        db.add(SystemSetting(key=key, value=value))


def default_json_body_mb() -> int:
    """MAX_JSON_BODY_BYTES rounded up to whole megabytes (nginx granularity)."""
    return max(1, -(-int(get_settings().max_json_body_bytes) // (1024 * 1024)))


def nginx_conf_matches(text: str, *, max_body_mb: int, json_body_mb: int | None = None) -> bool:
    """True when a rendered nginx.conf already carries both body ceilings.

    The reconcile used to compare only the http-level (upload) ceiling, so a
    change of MAX_JSON_BODY_BYTES alone never reached the edge until the
    upload ceiling happened to move too.
    """
    match = _NGINX_BODY_RE.search(text)
    if not match or int(match.group(1)) != int(max_body_mb):
        return False
    json_mb = default_json_body_mb() if json_body_mb is None else int(json_body_mb)
    json_mb = max(1, min(json_mb, max(1, int(max_body_mb))))
    return f"client_max_body_size {json_mb}m;" in text


def read_nginx_client_max_body_mb(conf_path: Path | None = None) -> int | None:
    path = conf_path or (tls_state_dir() / "nginx.conf")
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    match = _NGINX_BODY_RE.search(text)
    if not match:
        return None
    try:
        return max(1, int(match.group(1)))
    except ValueError:
        return None


async def _resolve_edge_body_mb(db: AsyncSession) -> int:
    from app.services.request_body_limit_service import (
        resolve_request_body_limit_mb_from_limits,
    )
    from app.services.transfer_limits_service import get_transfer_limits

    limits = await get_transfer_limits(db)
    return resolve_request_body_limit_mb_from_limits(limits)


async def sync_edge_body_limit(db: AsyncSession) -> dict[str, Any]:
    """Publish the shared request ceiling and queue an edge reload when needed.

    Never waits for nginx apply (edge polls desired-state asynchronously).
    Safe to call after Storage transfer-limit saves and on startup reconcile.
    """
    from app.services.request_body_limit_service import publish_request_body_limit_mb

    body_mb = await _resolve_edge_body_mb(db)
    try:
        publish_request_body_limit_mb(body_mb)
    except OSError as exc:
        LOGGER.warning("Failed to publish shared request body limit: %s", exc)
        return {
            "attempted": True,
            "queued": False,
            "applied": False,
            "body_mb": body_mb,
            "reason": "publish_failed",
            "error": str(exc),
        }

    desired = read_desired_state()
    if not desired.get("enabled"):
        return {
            "attempted": False,
            "queued": False,
            "applied": False,
            "body_mb": body_mb,
            "reason": "https_disabled",
        }

    conf_path = tls_state_dir() / "nginx.conf"
    current_text = ""
    if conf_path.is_file():
        try:
            current_text = conf_path.read_text(encoding="utf-8")
        except OSError:
            current_text = ""
    if current_text and nginx_conf_matches(current_text, max_body_mb=body_mb):
        return {
            "attempted": True,
            "queued": False,
            "applied": True,
            "body_mb": body_mb,
            "generation": int(desired.get("generation") or 0),
            "reason": "unchanged",
        }

    https_port = int(desired.get("https_port") or 0)
    http_mode_raw = str(desired.get("http_mode") or "loopback_only")
    http_mode: HttpMode = (
        "redirect" if http_mode_raw == "redirect" else "loopback_only"
    )
    hsts_enabled = bool(desired.get("hsts"))
    certificate_id = desired.get("certificate_id")
    if not https_port or not certificate_id:
        return {
            "attempted": True,
            "queued": False,
            "applied": False,
            "body_mb": body_mb,
            "reason": "tls_state_incomplete",
        }

    try:
        cert = await get_certificate(db, int(certificate_id))
    except Exception as exc:
        LOGGER.warning("Edge body sync could not load certificate: %s", exc)
        return {
            "attempted": True,
            "queued": False,
            "applied": False,
            "body_mb": body_mb,
            "reason": "certificate_unavailable",
            "error": str(exc),
        }

    nginx = render_nginx_config(
        https_port=https_port,
        http_mode=http_mode,
        hsts_enabled=hsts_enabled,
        has_chain=bool(cert.chain_pem),
        max_body_mb=body_mb,
    )
    try:
        atomic_write(tls_state_dir() / "nginx.conf", nginx, mode=0o644)
    except OSError as exc:
        LOGGER.warning("Failed to rewrite edge nginx.conf: %s", exc)
        return {
            "attempted": True,
            "queued": False,
            "applied": False,
            "body_mb": body_mb,
            "reason": "nginx_write_failed",
            "error": str(exc),
        }

    generation = await _next_generation(db)
    await db.commit()
    write_desired_state(
        {
            "enabled": True,
            "generation": generation,
            "https_port": https_port,
            "http_mode": http_mode,
            "hsts": hsts_enabled,
            "fingerprint": desired.get("fingerprint") or cert.sha256_fingerprint,
            "certificate_id": cert.id,
        }
    )
    return {
        "attempted": True,
        "queued": True,
        "applied": False,
        "body_mb": body_mb,
        "generation": generation,
        "reason": "queued",
    }


async def reconcile_edge_body_limit(db: AsyncSession) -> dict[str, Any]:
    """Startup/admin reconcile: publish limits and refresh edge conf if needed."""
    try:
        return await sync_edge_body_limit(db)
    except Exception as exc:
        LOGGER.warning("Edge body-limit reconcile failed: %s", exc)
        return {
            "attempted": True,
            "queued": False,
            "applied": False,
            "reason": "reconcile_failed",
            "error": str(exc),
        }


async def activate_https(
    db: AsyncSession,
    *,
    certificate_id: int,
    https_port: int,
    http_mode: HttpMode,
    hsts_enabled: bool,
) -> dict[str, Any]:
    from app.services.request_body_limit_service import publish_request_body_limit_mb

    port = validate_https_port(https_port)
    if http_mode not in {"redirect", "loopback_only"}:
        raise TlsCertificateError("HTTP mode must be redirect or loopback_only.")
    cert = await get_certificate(db, certificate_id)
    key_pem = decrypt_private_key(cert)
    if not key_pem:
        raise TlsCertificateError("The stored private key could not be decrypted.")
    max_body_mb = await _resolve_edge_body_mb(db)
    try:
        publish_request_body_limit_mb(max_body_mb)
    except OSError as exc:
        LOGGER.warning("Failed to publish request body limit during HTTPS activate: %s", exc)
    nginx = render_nginx_config(
        https_port=port,
        http_mode=http_mode,
        hsts_enabled=bool(hsts_enabled),
        has_chain=bool(cert.chain_pem),
        max_body_mb=max_body_mb,
    )
    # Certificate and nginx.conf are inert until desired-state.json is bumped,
    # so they are written first, the database is committed next, and the edge is
    # only triggered once the new state is durable.
    materialize_certificate_files(cert.cert_pem, key_pem, cert.chain_pem)
    atomic_write(tls_state_dir() / "nginx.conf", nginx, mode=0o644)
    active_rows = (await db.execute(select(TlsCertificate))).scalars().all()
    for row in active_rows:
        row.is_active = row.id == cert.id
    await _set_setting(db, KEY_HTTPS_PORT, str(port))
    await _set_setting(db, KEY_HTTP_MODE, http_mode)
    await _set_setting(db, KEY_HSTS, "true" if hsts_enabled else "false")
    generation = await _next_generation(db)
    await db.commit()
    write_desired_state(
        {
            "enabled": True,
            "generation": generation,
            "https_port": port,
            "http_mode": http_mode,
            "hsts": bool(hsts_enabled),
            "fingerprint": cert.sha256_fingerprint,
            "certificate_id": cert.id,
        }
    )
    return tls_status_payload(active_certificate=cert, https_port=port, http_mode=http_mode, hsts=hsts_enabled)


async def deactivate_https(db: AsyncSession) -> dict[str, Any]:
    rows = (await db.execute(select(TlsCertificate))).scalars().all()
    for row in rows:
        row.is_active = False
    generation = await _next_generation(db)
    await db.commit()
    write_desired_state({"enabled": False, "generation": generation})
    wipe_materialized_certificate_files()
    return tls_status_payload(active_certificate=None, https_port=None, http_mode="loopback_only", hsts=False)


def tls_status_payload(
    *,
    active_certificate: TlsCertificate | None,
    https_port: int | None,
    http_mode: str,
    hsts: bool,
) -> dict[str, Any]:
    desired = read_desired_state()
    settings = get_settings()
    bind = (getattr(settings, "alpharouter_http_bind", "0.0.0.0") or "0.0.0.0").strip() or "0.0.0.0"
    days = None
    if active_certificate and active_certificate.not_after:
        from datetime import datetime

        days = int((active_certificate.not_after - datetime.utcnow()).total_seconds() // 86400)
    return {
        "enabled": bool(desired.get("enabled")),
        "generation": int(desired.get("generation") or 0),
        "https_port": https_port or desired.get("https_port"),
        "http_mode": desired.get("http_mode") or http_mode,
        "hsts": bool(desired.get("hsts", hsts)),
        "fingerprint": desired.get("fingerprint"),
        "certificate_id": desired.get("certificate_id") or (active_certificate.id if active_certificate else None),
        "days_remaining": days,
        "http_bind": bind,
        "http_published_on_all_interfaces": bind in {"0.0.0.0", "::", "*"},
        "apply_status": read_apply_status(),
    }


async def current_tls_status(db: AsyncSession) -> dict[str, Any]:
    row = (
        await db.execute(select(TlsCertificate).where(TlsCertificate.is_active.is_(True)))
    ).scalars().first()
    desired = read_desired_state()
    return tls_status_payload(
        active_certificate=row,
        https_port=desired.get("https_port"),
        http_mode=str(desired.get("http_mode") or "loopback_only"),
        hsts=bool(desired.get("hsts")),
    )


def tls_health_url(host: str, port: int) -> str:
    token = (host or "").strip()
    if ":" in token and not token.startswith("["):
        token = f"[{token}]"
    return f"https://{token}:{int(port)}/health"


def tls_health_probe_hosts() -> list[str]:
    """Hosts the app container can use to reach the host-network TLS edge."""
    hosts: list[str] = []
    seen: set[str] = set()

    def _add(value: str) -> None:
        token = (value or "").strip()
        if not token or token in seen:
            return
        seen.add(token)
        hosts.append(token)

    _add("127.0.0.1")
    _add("::1")
    _add("host.docker.internal")
    for network in local_gateway_networks():
        _add(str(network.network_address))
    return hosts


def edge_listener_applied() -> bool:
    desired = read_desired_state()
    if not desired.get("enabled"):
        return False
    status = read_apply_status()
    if not status or not status.get("ok"):
        return False
    try:
        return int(status.get("generation") or 0) == int(desired.get("generation") or 0)
    except (TypeError, ValueError):
        return False
