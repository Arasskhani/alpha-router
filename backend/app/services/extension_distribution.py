"""The browser extension as this server hands it out.

Puts the pieces together for the endpoints: where the neutral build is, which
origin the extension belongs to, the installation's key, the admin's settings
and the version - and, from those, the ZIP, the CRX, update.xml and the value
IT pastes into Group Policy. Anything that makes a download impossible is an
:class:`ExtensionUnavailable` with a reason a person can act on.
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy.ext.asyncio import AsyncSession

from app.branding import PRODUCT_NAME
from app.config import get_settings
from app.services.extension_keys import ExtensionKey, ExtensionKeyUnavailable, load_or_create_signing_key
from app.services.extension_package import (
    build_crx3,
    build_manifest,
    build_zip,
    crx_url,
    extension_config,
    extension_version,
    load_template,
    normalize_origin,
    package_files,
    read_dist,
    update_manifest_xml,
    update_url,
)
from app.services.extension_settings import ExtensionSettings, load_extension_settings

UNAVAILABLE_NOT_BUILT = "not_built"
UNAVAILABLE_KEY_UNREADABLE = "key_unreadable"
UNAVAILABLE_FRONTEND_URL = "frontend_url"


class ExtensionUnavailable(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def resolve_extension_dist(services_file: Path | None = None) -> Path:
    """The neutral build: /app/frontend/dist-extension in the image, frontend/dist-extension in a checkout."""
    backend_root = (services_file or Path(__file__)).resolve().parent.parent.parent
    candidates = (
        backend_root / "frontend" / "dist-extension",
        backend_root.parent / "frontend" / "dist-extension",
    )
    for path in candidates:
        if path.is_dir():
            return path
    return candidates[1]


def _is_loopback(host: str | None) -> bool:
    name = (host or "").strip("[]").lower()
    if not name or name == "localhost" or name.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(name).is_loopback
    except ValueError:
        return False


def server_origin(request_host: str | None) -> str:
    """FRONTEND_URL's origin, which every copy of the extension talks to.

    Never the request's own Host: forwarded headers are trusted only from known
    proxies, so an HTTPS install could come out as http, and the public CRX
    would follow whatever Host header a caller sent. FRONTEND_URL defaults to
    a loopback address; left like that on a server people reach by another
    name, a download would point every browser at itself, so it is refused.
    """
    configured = get_settings().frontend_url
    try:
        origin = normalize_origin(configured)
    except ValueError as exc:
        raise ExtensionUnavailable(
            UNAVAILABLE_FRONTEND_URL,
            f"FRONTEND_URL ({configured!r}) is not a usable http(s) address.",
        ) from exc
    if _is_loopback(urlsplit(origin).hostname) and not _is_loopback(request_host):
        raise ExtensionUnavailable(
            UNAVAILABLE_FRONTEND_URL,
            f"FRONTEND_URL is {origin}. Set it to the address people use for this server, then restart it.",
        )
    return origin


@dataclass(frozen=True)
class ExtensionBuild:
    origin: str
    version: str
    version_name: str
    key: ExtensionKey
    settings: ExtensionSettings
    files: dict[str, bytes]

    @property
    def extension_id(self) -> str:
        return self.key.extension_id

    @property
    def update_url(self) -> str:
        return update_url(self.origin)

    @property
    def gpo_value(self) -> str:
        """One line of ExtensionInstallForcelist (Chrome and Edge alike)."""
        return f"{self.extension_id};{self.update_url}"


async def current_build(db: AsyncSession, *, request_host: str | None) -> ExtensionBuild:
    """Everything a download needs, or ExtensionUnavailable saying why not."""
    dist = resolve_extension_dist()
    try:
        files = read_dist(dist)
        template = load_template(files)
    except (FileNotFoundError, ValueError) as exc:
        raise ExtensionUnavailable(
            UNAVAILABLE_NOT_BUILT,
            "The browser extension is not built on this server. Rebuild the image (npm run build builds it).",
        ) from exc
    origin = server_origin(request_host)
    try:
        key = await load_or_create_signing_key(db)
    except ExtensionKeyUnavailable as exc:
        raise ExtensionUnavailable(UNAVAILABLE_KEY_UNREADABLE, str(exc)) from exc
    settings = await load_extension_settings(db)
    app_version = get_settings().app_version.strip()
    version = extension_version(app_version, settings.manifest_revision)
    version_name = app_version or "development"
    manifest = build_manifest(
        template,
        version=version,
        version_name=version_name,
        public_key_b64=key.public_key_b64,
        origin=origin,
        site_access=settings.site_access,
    )
    config = extension_config(origin=origin, server_name=PRODUCT_NAME, version=version)
    return ExtensionBuild(
        origin=origin,
        version=version,
        version_name=version_name,
        key=key,
        settings=settings,
        files=package_files(files, manifest=manifest, config=config),
    )


def zip_bytes(build: ExtensionBuild) -> bytes:
    return build_zip(build.files)


def crx_bytes(build: ExtensionBuild) -> bytes:
    return build_crx3(build_zip(build.files), build.key)


def update_xml(build: ExtensionBuild) -> str:
    return update_manifest_xml(
        extension_id=build.extension_id,
        codebase=crx_url(build.origin, build.version),
        version=build.version,
    )


def distribution_payload(build: ExtensionBuild | None, unavailable: ExtensionUnavailable | None) -> dict[str, Any]:
    """What the Settings tab and the admin card show about the extension this server hands out."""
    if build is None:
        return {
            "available": False,
            "reason_code": unavailable.code if unavailable else UNAVAILABLE_NOT_BUILT,
            "reason": unavailable.message if unavailable else None,
            "version": None,
            "extension_id": None,
            "update_url": None,
            "gpo_value": None,
            "server_url": None,
        }
    return {
        "available": True,
        "reason_code": None,
        "reason": None,
        "version": build.version,
        "extension_id": build.extension_id,
        "update_url": build.update_url,
        "gpo_value": build.gpo_value,
        "server_url": build.origin,
    }
