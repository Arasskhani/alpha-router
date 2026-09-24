"""The browser extension as this server hands it out.

Puts the pieces together for the endpoints: where the neutral build is, which
origin the extension belongs to, the installation's key, the admin's settings
and the version - and, from those, the ZIP, the CRX, update.xml and the value
IT pastes into Group Policy. Anything that makes a download impossible is an
:class:`ExtensionUnavailable` with a reason a person can act on.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import threading
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlsplit

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.branding import PRODUCT_NAME
from app.config import get_settings
from app.database import AsyncSessionLocal
from app.models.system import SystemSetting
from app.services.extension_keys import ExtensionKey, ExtensionKeyUnavailable, load_or_create_signing_key
from app.services.extension_package import (
    MAX_PACKAGE_REVISION,
    build_crx3,
    build_manifest,
    build_zip,
    crx_url,
    extension_config,
    extension_version,
    load_template,
    normalize_origin,
    package_files,
    package_fingerprint,
    read_dist,
    update_manifest_xml,
    update_url,
)
from app.services.extension_settings import ExtensionSettings, load_extension_settings

UNAVAILABLE_NOT_BUILT = "not_built"
UNAVAILABLE_KEY_UNREADABLE = "key_unreadable"
UNAVAILABLE_FRONTEND_URL = "frontend_url"

#: ``{"latest": n, "recent": {fingerprint: revision}}``: the package's revision
#: counter, and the revisions of the last few fingerprints seen.
PACKAGE_KEY = "extension.package"
#: Fingerprints remembered with their revision. Two builds answering at once
#: (old and new workers during an upgrade) then keep their numbers instead of
#: bumping the counter on every request.
_RECENT_FINGERPRINTS = 3


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


def _ip(host: str | None) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        return ipaddress.ip_address((host or "").strip("[]"))
    except ValueError:
        return None


def _is_loopback(host: str | None) -> bool:
    name = (host or "").strip("[]").lower()
    if not name or name == "localhost" or name.endswith(".localhost"):
        return True
    address = _ip(name)
    return bool(address and address.is_loopback)


def server_origin(request_host: str | None, client_ip: str | None = None) -> str:
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
    host = urlsplit(origin).hostname
    address = _ip(host)
    if address is not None and address.is_unspecified:
        raise ExtensionUnavailable(
            UNAVAILABLE_FRONTEND_URL,
            f"FRONTEND_URL is {origin}, an address to listen on, not one a browser can reach. "
            "Set it to the address people use for this server, then restart it.",
        )
    # Loopback is right only when the person asking is on this machine too:
    # by the name they used, and by where the request came from (a proxy on
    # the same host can send Host: 127.0.0.1 for a visitor from anywhere).
    asked_from_elsewhere = not _is_loopback(request_host) or (client_ip is not None and not _is_loopback(client_ip))
    if _is_loopback(host) and asked_from_elsewhere:
        raise ExtensionUnavailable(
            UNAVAILABLE_FRONTEND_URL,
            f"FRONTEND_URL is {origin}. Set it to the address people use for this server, then restart it.",
        )
    return origin


def _parse_package_state(raw: str | None) -> tuple[int, dict[str, int]]:
    try:
        data = json.loads(raw or "")
        latest = int(data["latest"])
        recent = {str(fp): int(rev) for fp, rev in dict(data["recent"]).items()}
    except (ValueError, TypeError, KeyError):
        return 0, {}
    return latest, recent


async def package_revision(fingerprint: str) -> int:
    """The revision of the package with this fingerprint; a new fingerprint gets the next number.

    Committed in a session of its own (a version handed out must not be rolled
    back with the request) and with a compare-and-set update, so two workers
    that see the same new build agree on one number.
    """
    async with AsyncSessionLocal() as session:
        for _ in range(8):
            row = await session.get(SystemSetting, PACKAGE_KEY, populate_existing=True)
            stored = cast("str | None", row.value) if row is not None else None
            latest, recent = _parse_package_state(stored)
            if fingerprint in recent:
                return recent[fingerprint]
            revision = latest + 1
            if revision > MAX_PACKAGE_REVISION:
                raise ExtensionUnavailable(UNAVAILABLE_NOT_BUILT, "The extension's version counter is exhausted.")
            recent[fingerprint] = revision
            kept = dict(sorted(recent.items(), key=lambda item: item[1])[-_RECENT_FINGERPRINTS:])
            value = json.dumps({"latest": revision, "recent": kept}, sort_keys=True)
            if row is None:
                session.add(SystemSetting(key=PACKAGE_KEY, value=value))
                try:
                    await session.commit()
                except IntegrityError:
                    await session.rollback()
                    continue
                return revision
            result = await session.execute(
                update(SystemSetting)
                .where(SystemSetting.key == PACKAGE_KEY, SystemSetting.value == stored)
                .values(value=value)
            )
            await session.commit()
            if int(getattr(result, "rowcount", 0) or 0) == 1:
                return revision
    raise ExtensionUnavailable(UNAVAILABLE_NOT_BUILT, "The extension's version could not be recorded; try again.")


@dataclass(frozen=True)
class _DistSnapshot:
    #: (path, size, mtime) of every file: when it is unchanged, so are the files.
    signature: tuple[tuple[str, int, int], ...]
    files: dict[str, bytes]


_dist_snapshots: dict[Path, _DistSnapshot] = {}
_ARTIFACT_CACHE_SIZE = 8
_artifacts: OrderedDict[tuple[str, ...], bytes] = OrderedDict()
_artifacts_lock = threading.Lock()


def _dist_signature(dist: Path) -> tuple[tuple[str, int, int], ...]:
    entries = []
    for path in dist.rglob("*"):
        if path.is_file():
            stat = path.stat()
            entries.append((path.relative_to(dist).as_posix(), stat.st_size, stat.st_mtime_ns))
    return tuple(sorted(entries))


def _dist_files(dist: Path) -> dict[str, bytes]:
    """The built files, read again only when one of them changed."""
    signature = _dist_signature(dist) if dist.is_dir() else ()
    cached = _dist_snapshots.get(dist)
    if cached is not None and cached.signature == signature:
        return cached.files
    files = read_dist(dist)
    _dist_snapshots[dist] = _DistSnapshot(signature=signature, files=files)
    return files


@dataclass(frozen=True)
class ExtensionBuild:
    origin: str
    version: str
    key: ExtensionKey
    settings: ExtensionSettings
    files: dict[str, bytes]
    #: What the package is made from; with the version and the key, it names the bytes.
    fingerprint: str

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


async def current_build(db: AsyncSession, *, request_host: str | None, client_ip: str | None = None) -> ExtensionBuild:
    """Everything a download needs, or ExtensionUnavailable saying why not."""
    dist = resolve_extension_dist()
    try:
        files = _dist_files(dist)
        template = load_template(files)
    except (FileNotFoundError, ValueError) as exc:
        raise ExtensionUnavailable(
            UNAVAILABLE_NOT_BUILT,
            "The browser extension is not built on this server. Rebuild the image (npm run build builds it).",
        ) from exc
    origin = server_origin(request_host, client_ip)
    try:
        key = await load_or_create_signing_key(db)
    except ExtensionKeyUnavailable as exc:
        raise ExtensionUnavailable(UNAVAILABLE_KEY_UNREADABLE, str(exc)) from exc
    settings = await load_extension_settings(db)
    fingerprint = package_fingerprint(files, origin=origin, site_access=settings.site_access, server_name=PRODUCT_NAME)
    version = extension_version(await package_revision(fingerprint))
    manifest = build_manifest(
        template,
        version=version,
        public_key_b64=key.public_key_b64,
        origin=origin,
        site_access=settings.site_access,
    )
    config = extension_config(origin=origin, server_name=PRODUCT_NAME, version=version)
    return ExtensionBuild(
        origin=origin,
        version=version,
        key=key,
        settings=settings,
        files=package_files(files, manifest=manifest, config=config),
        fingerprint=fingerprint,
    )


def _artifact(kind: str, build: ExtensionBuild, make) -> bytes:
    """Build each ZIP and CRX once: anyone may ask for the CRX, and signing is not free."""
    key = (kind, build.fingerprint, build.version, build.extension_id)
    with _artifacts_lock:
        cached = _artifacts.get(key)
        if cached is not None:
            _artifacts.move_to_end(key)
            return cached
    data = make()
    with _artifacts_lock:
        _artifacts[key] = data
        _artifacts.move_to_end(key)
        while len(_artifacts) > _ARTIFACT_CACHE_SIZE:
            _artifacts.popitem(last=False)
    return data


async def zip_bytes(build: ExtensionBuild) -> bytes:
    # Off the event loop: compressing the build must not stall chat streams.
    return await asyncio.to_thread(_artifact, "zip", build, lambda: build_zip(build.files))


async def crx_bytes(build: ExtensionBuild) -> bytes:
    return await asyncio.to_thread(
        _artifact, "crx", build, lambda: build_crx3(_artifact("zip", build, lambda: build_zip(build.files)), build.key)
    )


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
