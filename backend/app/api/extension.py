"""The browser extension: what the web app shows about it, the download, and self-hosted updates.

``/api/extension/info`` and ``/api/extension/download`` are for a signed-in
user (Settings → Extension). ``/extension/update.xml`` and the CRX it points to
are public on purpose: Chrome's and Edge's updaters fetch them without a user
session when Group Policy force-installs the extension. They carry nothing
secret - the public key and code any installed copy already holds.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_active_user
from app.database import get_db
from app.models.user import User
from app.services.chat_tool_access_service import permitted_tool_keys
from app.services.extension_distribution import (
    ExtensionBuild,
    ExtensionUnavailable,
    crx_bytes,
    current_build,
    distribution_payload,
    update_xml,
    zip_bytes,
)
from app.services.resource_access_service import resolve_resource_access_subject

router = APIRouter(tags=["extension"])

EXTENSION_TOOL = "browser_extension"
_NO_STORE = {"Cache-Control": "no-store"}
_NO_CACHE = {"Cache-Control": "no-cache"}


async def extension_permitted(db: AsyncSession, user: User) -> bool:
    """The Chat Tools ACL for the browser extension, for an active account."""
    if not user.is_active:
        return False
    subject = await resolve_resource_access_subject(db, user_id=int(user.id))
    return EXTENSION_TOOL in await permitted_tool_keys(db, subject, keys=[EXTENSION_TOOL])


async def _build_or_none(
    db: AsyncSession, request: Request
) -> tuple[ExtensionBuild | None, ExtensionUnavailable | None]:
    try:
        return await current_build(db, request_host=request.url.hostname), None
    except ExtensionUnavailable as exc:
        return None, exc


@router.get("/api/extension/info")
async def extension_info(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Whether this account may use the extension, and what this server hands out."""
    build, unavailable = await _build_or_none(db, request)
    payload = distribution_payload(build, unavailable)
    payload["permitted"] = await extension_permitted(db, user)
    payload["site_access"] = build.settings.site_access if build is not None else None
    return payload


@router.get("/api/extension/download")
async def download_extension(
    request: Request,
    user: User = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """The extension for this server, as a ZIP for Load unpacked."""
    if not await extension_permitted(db, user):
        raise HTTPException(status_code=403, detail="The browser extension is not enabled for your account.")
    build, unavailable = await _build_or_none(db, request)
    if build is None:
        raise HTTPException(status_code=503, detail=unavailable.message if unavailable else "Unavailable")
    return Response(
        content=zip_bytes(build),
        media_type="application/zip",
        headers={
            **_NO_STORE,
            "Content-Disposition": f'attachment; filename="alpharouter-extension-{build.version}.zip"',
        },
    )


@router.get("/extension/update.xml", include_in_schema=False)
async def extension_update_manifest(request: Request, db: AsyncSession = Depends(get_db)) -> Response:
    build, _ = await _build_or_none(db, request)
    if build is None:
        raise HTTPException(status_code=404, detail="Not Found")
    return Response(content=update_xml(build), media_type="application/xml", headers=_NO_CACHE)


@router.get("/extension/alpharouter.crx", include_in_schema=False)
async def extension_crx(request: Request, db: AsyncSession = Depends(get_db)) -> Response:
    build, _ = await _build_or_none(db, request)
    if build is None:
        raise HTTPException(status_code=404, detail="Not Found")
    return Response(content=crx_bytes(build), media_type="application/x-chrome-extension", headers=_NO_CACHE)
