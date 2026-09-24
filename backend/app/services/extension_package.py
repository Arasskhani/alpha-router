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

The version is not the app's version. A policy-installed copy updates only when
update.xml offers a higher version, and it must update whenever the package
changes: new code (with or without a new git tag), another site-access mode,
another origin. So the server numbers the package itself - a revision that
grows each time the package's fingerprint changes (extension_distribution) -
and the version is ``1.0.<high>.<low>`` of that revision. It also keeps the
app's exact build out of a file anyone can download.
"""

from __future__ import annotations

import copy
import hashlib
import io
import json
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
#: The first number of every version; raised only to start the count again.
VERSION_MAJOR = 1
MAX_PACKAGE_REVISION = MAX_VERSION_PART * 65536 + MAX_VERSION_PART

CONNECTED_PAGE = "connected.html"
UPDATE_PATH = "/extension/update.xml"
CRX_PATH = "/extension/alpharouter.crx"

_FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)


def extension_version(revision: int) -> str:
    """``1.0.<high>.<low>`` of the package revision (1 and up)."""
    if not 1 <= int(revision) <= MAX_PACKAGE_REVISION:
        raise ValueError(f"package revision must be 1..{MAX_PACKAGE_REVISION}")
    return f"{VERSION_MAJOR}.0.{int(revision) // 65536}.{int(revision) % 65536}"


def package_fingerprint(files: Mapping[str, bytes], *, origin: str, site_access: str, server_name: str) -> str:
    """What the package is made from: the built files and everything the server patches in."""
    digest = hashlib.sha256()
    for name in sorted(files):
        digest.update(name.encode("utf-8") + b"\0" + hashlib.sha256(files[name]).digest())
    inputs = {"origin": origin, "site_access": site_access, "server_name": server_name}
    digest.update(json.dumps(inputs, sort_keys=True).encode("utf-8"))
    return digest.hexdigest()


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
    # Never the app's build (a git describe string) in a file anyone can fetch.
    manifest.pop("version_name", None)
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
