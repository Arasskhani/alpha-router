"""Turn the built extension into what a browser installs.

``npm run build`` leaves a neutral build in ``frontend/dist-extension``: a
manifest that belongs to no server and a ``config.json`` that points nowhere.
What a browser actually loads is made from it here, per server:

- the manifest gets this installation's public key (so its ID is this
  server's), the server's origin as a host permission and as the only origin
  allowed to open ``connected.html``, the site-access mode the admin chose,
  a version, and the update URL;
- ``config.json`` names the server, so nobody types an address;
- a ZIP of that, for Load unpacked; and the same ZIP signed as a CRX3, with an
  ``update.xml`` pointing at it, for Group Policy.

The ZIP is byte-for-byte reproducible (sorted entries, fixed timestamps), and
the CRX3 is written by hand from its specification: a protobuf header with one
RSA SHA-256 proof, then the ZIP.
"""

from __future__ import annotations

import copy
import hashlib
import io
import json
import re
import struct
import zipfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from xml.sax.saxutils import quoteattr

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding

from app.services.extension_keys import ExtensionKey

SITE_ACCESS_PER_SITE = "per_site"
SITE_ACCESS_ALL_SITES = "all_sites"
SITE_ACCESS_MODES = (SITE_ACCESS_PER_SITE, SITE_ACCESS_ALL_SITES)

#: Chrome accepts up to four dot-separated integers, each 0-65535.
MAX_VERSION_PART = 65535
#: The fourth number is the manifest revision for a pre-release build and this
#: plus the revision for a release, so a release always updates a pre-release
#: of the same A.B.C.
RELEASE_OFFSET = 32768
MAX_MANIFEST_REVISION = RELEASE_OFFSET - 1

CONNECTED_PAGE = "connected.html"
UPDATE_PATH = "/extension/update.xml"
CRX_PATH = "/extension/alpharouter.crx"

_VERSION_RE = re.compile(r"^\s*v?(\d+)(?:\.(\d+))?(?:\.(\d+))?(.*)$")
#: A semver pre-release right after the numbers (``-rc.1``, ``-beta2``). A
#: ``git describe`` suffix (``-5-gabc1234``, ``-dirty``) is code at or after
#: the tag and is not one.
_PRERELEASE_RE = re.compile(r"^-(?:rc|alpha|beta|pre|preview|dev)(?![a-z])", re.IGNORECASE)
_FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)


def extension_version(app_version: str | None, revision: int) -> str:
    """``A.B.C.X`` for the manifest, from APP_VERSION and the manifest revision."""
    if not 0 <= int(revision) <= MAX_MANIFEST_REVISION:
        raise ValueError(f"manifest revision must be 0..{MAX_MANIFEST_REVISION}")
    match = _VERSION_RE.match(app_version or "")
    if match is None:
        # No version at all ("", a bare commit id): below any real release.
        return f"0.0.0.{int(revision)}"
    parts = [min(int(group or 0), MAX_VERSION_PART) for group in match.groups()[:3]]
    prerelease = bool(_PRERELEASE_RE.match(match.group(4) or ""))
    fourth = int(revision) if prerelease else RELEASE_OFFSET + int(revision)
    return f"{parts[0]}.{parts[1]}.{parts[2]}.{fourth}"


def normalize_origin(url: str) -> str:
    """``scheme://host[:port]`` of an http(s) URL, lower-case, default port dropped."""
    parts = urlsplit((url or "").strip())
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https") or not parts.hostname:
        raise ValueError(f"not an http(s) URL: {url!r}")
    if parts.username is not None or parts.password is not None:
        raise ValueError("a server URL cannot carry a user name or password")
    host = parts.hostname.lower()
    if ":" in host:  # IPv6 literal
        host = f"[{host}]"
    port = parts.port
    if port is None or (scheme, port) in (("http", 80), ("https", 443)):
        return f"{scheme}://{host}"
    return f"{scheme}://{host}:{port}"


def update_url(origin: str) -> str:
    return f"{origin}{UPDATE_PATH}"


def crx_url(origin: str, version: str) -> str:
    # The version in the link: Chrome refuses a CRX whose version is not the
    # one update.xml promised, so a cached old file must never answer.
    return f"{origin}{CRX_PATH}?v={version}"


def build_manifest(
    template: Mapping[str, Any],
    *,
    version: str,
    version_name: str,
    public_key_b64: str,
    origin: str,
    site_access: str,
) -> dict[str, Any]:
    """The template with everything that makes it this server's extension."""
    if site_access not in SITE_ACCESS_MODES:
        raise ValueError(f"unknown site access mode {site_access!r}")
    manifest = copy.deepcopy(dict(template))
    server_pattern = f"{origin}/*"
    manifest["version"] = version
    manifest["version_name"] = version_name
    manifest["key"] = public_key_b64
    hosts = [server_pattern]
    if site_access == SITE_ACCESS_ALL_SITES:
        hosts.append("<all_urls>")
        manifest.pop("optional_host_permissions", None)
    else:
        manifest["optional_host_permissions"] = ["<all_urls>"]
    manifest["host_permissions"] = hosts
    manifest["web_accessible_resources"] = [{"resources": [CONNECTED_PAGE], "matches": [server_pattern]}]
    manifest["update_url"] = update_url(origin)
    return manifest


def extension_config(*, origin: str, server_name: str, version: str) -> dict[str, str]:
    """``config.json``: which server this copy belongs to."""
    return {"serverUrl": origin, "serverName": server_name, "extensionVersion": version}


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def read_dist(dist_dir: Path) -> dict[str, bytes]:
    """Every file of a built extension by its POSIX path relative to the folder."""
    root = Path(dist_dir)
    if not (root / "manifest.json").is_file():
        raise FileNotFoundError(f"no built extension in {root}")
    files: dict[str, bytes] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            files[path.relative_to(root).as_posix()] = path.read_bytes()
    return files


def load_template(files: Mapping[str, bytes]) -> dict[str, Any]:
    template = json.loads(files["manifest.json"].decode("utf-8"))
    if not isinstance(template, dict) or template.get("manifest_version") != 3:
        raise ValueError("the built manifest is not a Manifest V3 manifest")
    return template


def package_files(
    files: Mapping[str, bytes],
    *,
    manifest: Mapping[str, Any],
    config: Mapping[str, Any],
) -> dict[str, bytes]:
    """The built files with this server's manifest and config in place."""
    out = dict(files)
    out["manifest.json"] = _json_bytes(manifest)
    out["config.json"] = _json_bytes(config)
    return out


def build_zip(files: Mapping[str, bytes]) -> bytes:
    """A reproducible ZIP with every file at its root.

    No top folder: Windows "Extract All" (and macOS) already put the files in a
    folder named after the ZIP, which is the folder Load unpacked wants.
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(files):
            info = zipfile.ZipInfo(name, date_time=_FIXED_ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, files[name])
    return buffer.getvalue()


def _varint(value: int) -> bytes:
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def _length_delimited(field: int, data: bytes) -> bytes:
    return _varint((field << 3) | 2) + _varint(len(data)) + data


#: What a CRX3 signature covers before the header data and the archive.
CRX3_SIGNATURE_CONTEXT = b"CRX3 SignedData\x00"


def build_crx3(zip_bytes: bytes, key: ExtensionKey) -> bytes:
    """The ZIP as a CRX3 signed with this installation's key.

    CrxFileHeader: sha256_with_rsa (2) = AsymmetricKeyProof{public_key (1),
    signature (2)}; signed_header_data (10000) = SignedData{crx_id (1)}, the
    first 16 bytes of SHA-256 of the public key.
    """
    crx_id = hashlib.sha256(key.public_der).digest()[:16]
    signed_data = _length_delimited(1, crx_id)
    signature = key.private_key.sign(
        CRX3_SIGNATURE_CONTEXT + struct.pack("<I", len(signed_data)) + signed_data + zip_bytes,
        padding.PKCS1v15(),
        hashes.SHA256(),
    )
    proof = _length_delimited(1, key.public_der) + _length_delimited(2, signature)
    header = _length_delimited(2, proof) + _length_delimited(10000, signed_data)
    return b"Cr24" + struct.pack("<I", 3) + struct.pack("<I", len(header)) + header + zip_bytes


def update_manifest_xml(*, extension_id: str, codebase: str, version: str) -> str:
    """The gupdate response Chrome and Edge poll for a force-installed extension."""
    return (
        "<?xml version='1.0' encoding='UTF-8'?>\n"
        "<gupdate xmlns='http://www.google.com/update2/response' protocol='2.0'>\n"
        f"  <app appid={quoteattr(extension_id)}>\n"
        f"    <updatecheck codebase={quoteattr(codebase)} version={quoteattr(version)} />\n"
        "  </app>\n"
        "</gupdate>\n"
    )
