"""Admin Security Settings API — TLS and admin IP allowlist."""

from __future__ import annotations

from typing import Literal

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_security_settings, require_super_admin
from app.config import get_settings
from app.database import get_db
from app.models.user import User
from app.services.admin_ip_allowlist_service import (
    AllowlistError,
    add_entry,
    delete_entry,
    get_restriction_state,
    set_restriction_mode,
    update_entry,
)
from app.services.bounded_io import BoundedIOError, read_upload_bounded
from app.services.client_ip import resolve_client_ip
from app.services.security_audit import log_security_event
from app.services.tls_certificate_service import (
    MAX_CERT_UPLOAD_BYTES,
    TlsCertificateError,
    delete_certificate,
    get_certificate,
    list_certificates,
    parse_pem_bundle,
    parse_pkcs12,
    store_certificate,
)
from app.services.tls_edge_service import (
    activate_https,
    current_tls_status,
    deactivate_https,
    edge_listener_applied,
    tls_health_probe_hosts,
    tls_health_url,
    validate_https_port,
)

router = APIRouter(prefix="/api/admin/security", tags=["admin-security"])


class AllowlistCreate(BaseModel):
    cidr: str
    label: str = ""


class AllowlistPatch(BaseModel):
    label: str | None = None
    enabled: bool | None = None


class AllowlistModeIn(BaseModel):
    mode: Literal["off", "monitor", "enforce"]
    allow_loopback: bool | None = None


class TlsActivateIn(BaseModel):
    certificate_id: int
    https_port: int = Field(default=443, ge=1, le=65535)
    http_mode: Literal["redirect", "loopback_only"] = "loopback_only"
    hsts_enabled: bool = False


class TlsVerifyIn(BaseModel):
    https_port: int = Field(default=443, ge=1, le=65535)


def _http_error(exc: ValueError) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


@router.get("/ip-allowlist")
async def get_ip_allowlist(
    request: Request,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_security_settings),
):
    state = await get_restriction_state(db)
    return {
        "mode": state.mode,
        "allow_loopback": state.allow_loopback,
        "entries": list(state.entries),
        "detected_client_ip": resolve_client_ip(request),
        "kill_switch": bool(get_settings().admin_ip_restriction_disabled),
        "http_bind": get_settings().alpharouter_http_bind,
    }


@router.post("/ip-allowlist")
async def create_ip_allowlist_entry(
    body: AllowlistCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_super_admin),
):
    try:
        entry = await add_entry(
            db,
            cidr=body.cidr,
            label=body.label,
            created_by_user_id=user.id,
        )
    except AllowlistError as exc:
        raise _http_error(exc) from exc
    await log_security_event(
        db,
        actor=user,
        actor_ip=resolve_client_ip(request),
        action="allowlist_add",
        resource_type="admin_ip_allowlist",
        resource_id=str(entry["id"]),
        detail={"cidr": entry["cidr"], "label": entry["label"]},
    )
    return entry


@router.patch("/ip-allowlist/{entry_id}")
async def patch_ip_allowlist_entry(
    entry_id: int,
    body: AllowlistPatch,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_super_admin),
):
    try:
        entry = await update_entry(
            db,
            entry_id,
            label=body.label,
            enabled=body.enabled,
            client_ip=resolve_client_ip(request),
        )
    except AllowlistError as exc:
        raise _http_error(exc) from exc
    await log_security_event(
        db,
        actor=user,
        actor_ip=resolve_client_ip(request),
        action="allowlist_update",
        resource_type="admin_ip_allowlist",
        resource_id=str(entry_id),
        detail=body.model_dump(exclude_unset=True),
    )
    return entry


@router.delete("/ip-allowlist/{entry_id}")
async def remove_ip_allowlist_entry(
    entry_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_super_admin),
):
    try:
        await delete_entry(db, entry_id, client_ip=resolve_client_ip(request))
    except AllowlistError as exc:
        raise _http_error(exc) from exc
    await log_security_event(
        db,
        actor=user,
        actor_ip=resolve_client_ip(request),
        action="allowlist_delete",
        resource_type="admin_ip_allowlist",
        resource_id=str(entry_id),
    )
    return {"ok": True}


@router.put("/ip-allowlist/mode")
async def put_ip_allowlist_mode(
    body: AllowlistModeIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_super_admin),
):
    client_ip = resolve_client_ip(request)
    try:
        state = await set_restriction_mode(
            db,
            body.mode,
            client_ip=client_ip,
            allow_loopback=body.allow_loopback,
        )
    except AllowlistError as exc:
        raise HTTPException(
            status_code=400,
            detail={"message": str(exc), "detected_client_ip": client_ip},
        ) from exc
    await log_security_event(
        db,
        actor=user,
        actor_ip=client_ip,
        action="allowlist_mode",
        resource_type="admin_ip_allowlist",
        detail={"mode": state.mode, "allow_loopback": state.allow_loopback},
    )
    return {
        "mode": state.mode,
        "allow_loopback": state.allow_loopback,
        "entries": list(state.entries),
        "detected_client_ip": client_ip,
    }


@router.get("/tls/certificates")
async def get_tls_certificates(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_security_settings),
):
    return {"items": await list_certificates(db)}


@router.post("/tls/certificates")
async def upload_tls_certificate(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_super_admin),
    label: str = Form(""),
    password: str = Form(""),
    cert_pem: str = Form(""),
    key_pem: str = Form(""),
    chain_pem: str = Form(""),
    file: UploadFile | None = File(None),
):
    try:
        if file is not None and file.filename:
            raw = await read_upload_bounded(file, max_bytes=MAX_CERT_UPLOAD_BYTES)
            name = (file.filename or "").lower()
            if name.endswith((".p12", ".pfx")):
                parsed = parse_pkcs12(raw, password or None)
            else:
                text = raw.decode("utf-8", errors="replace")
                parsed = parse_pem_bundle(
                    cert_pem=text if "BEGIN CERTIFICATE" in text else cert_pem,
                    key_pem=text if "PRIVATE KEY" in text else key_pem,
                    chain_pem=chain_pem,
                    password=password or None,
                )
        else:
            if not cert_pem.strip() or not key_pem.strip():
                raise TlsCertificateError("Upload a PEM certificate and private key, or a PKCS#12 file.")
            if len(cert_pem.encode()) + len(key_pem.encode()) + len(chain_pem.encode()) > MAX_CERT_UPLOAD_BYTES:
                raise TlsCertificateError("Certificate files are too large (max 256 KB).")
            parsed = parse_pem_bundle(
                cert_pem=cert_pem,
                key_pem=key_pem,
                chain_pem=chain_pem,
                password=password or None,
            )
        stored = await store_certificate(db, parsed, label=label, uploaded_by_user_id=user.id)
    except BoundedIOError as exc:
        raise HTTPException(status_code=400, detail="Certificate files are too large (max 256 KB).") from exc
    except TlsCertificateError as exc:
        raise _http_error(exc) from exc
    await log_security_event(
        db,
        actor=user,
        actor_ip=resolve_client_ip(request),
        action="tls_upload",
        resource_type="tls_certificate",
        resource_id=str(stored["id"]),
        detail={"fingerprint": stored["sha256_fingerprint"], "label": stored["label"]},
    )
    return stored


@router.delete("/tls/certificates/{cert_id}")
async def remove_tls_certificate(
    cert_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_super_admin),
):
    try:
        await delete_certificate(db, cert_id)
    except TlsCertificateError as exc:
        raise _http_error(exc) from exc
    await log_security_event(
        db,
        actor=user,
        actor_ip=resolve_client_ip(request),
        action="tls_delete",
        resource_type="tls_certificate",
        resource_id=str(cert_id),
    )
    return {"ok": True}


@router.post("/tls/certificates/{cert_id}/validate")
async def validate_tls_certificate(
    cert_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_security_settings),
):
    try:
        row = await get_certificate(db, cert_id)
    except TlsCertificateError as exc:
        raise _http_error(exc) from exc
    return {
        "ok": True,
        "id": row.id,
        "sha256_fingerprint": row.sha256_fingerprint,
        "not_after": row.not_after.isoformat() + "Z" if row.not_after else None,
        "is_active": bool(row.is_active),
    }


@router.get("/tls/status")
async def get_tls_status(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_security_settings),
):
    return await current_tls_status(db)


@router.post("/tls/activate")
async def activate_tls(
    body: TlsActivateIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_super_admin),
):
    try:
        validate_https_port(body.https_port)
        status = await activate_https(
            db,
            certificate_id=body.certificate_id,
            https_port=body.https_port,
            http_mode=body.http_mode,
            hsts_enabled=body.hsts_enabled,
        )
    except TlsCertificateError as exc:
        raise _http_error(exc) from exc
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Could not write TLS state files: {exc}") from exc
    await log_security_event(
        db,
        actor=user,
        actor_ip=resolve_client_ip(request),
        action="tls_activate",
        resource_type="tls_certificate",
        resource_id=str(body.certificate_id),
        detail={"https_port": body.https_port, "http_mode": body.http_mode},
    )
    return status


@router.delete("/tls/active")
async def deactivate_tls(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_super_admin),
):
    try:
        status = await deactivate_https(db)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Could not write TLS state files: {exc}") from exc
    await log_security_event(
        db,
        actor=user,
        actor_ip=resolve_client_ip(request),
        action="tls_deactivate",
        resource_type="tls",
    )
    return status


@router.post("/tls/verify")
async def verify_tls_listener(
    body: TlsVerifyIn | None = None,
    _: User = Depends(require_security_settings),
):
    """Probe the HTTPS listener. POST only because it carries a port in the body.

    This changes nothing - no database session, no audit event, just an outbound
    request to the health URL - so it is gated like the other reads on this
    router rather than like the certificate operations around it. That also lets
    Read Only Super Admin confirm HTTPS is up, which is a question about state,
    not a change to it.
    """
    port = body.https_port if body and body.https_port else 443
    try:
        validate_https_port(int(port))
    except TlsCertificateError as exc:
        raise _http_error(exc) from exc
    last_error = "edge has not applied HTTPS yet"
    last_url = tls_health_url("127.0.0.1", port)
    async with httpx.AsyncClient(verify=False, timeout=3.0) as client:
        for host in tls_health_probe_hosts():
            url = tls_health_url(host, port)
            last_url = url
            try:
                response = await client.get(url)
            except httpx.HTTPError as exc:
                last_error = str(exc)
                continue
            if response.status_code == 200:
                return {"ok": True, "status_code": 200, "url": url, "source": "probe"}
            last_error = f"HTTP {response.status_code}"
    if edge_listener_applied():
        return {
            "ok": True,
            "status_code": None,
            "url": last_url,
            "source": "edge_apply_status",
        }
    return {"ok": False, "status_code": None, "url": last_url, "error": last_error}
