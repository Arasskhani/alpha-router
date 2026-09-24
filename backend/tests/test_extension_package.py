"""What a browser installs: the per-server manifest, the ZIP, the CRX3 and update.xml."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import struct
import zipfile
from xml.etree import ElementTree

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from app.services.extension_keys import ExtensionKey, extension_id_from_public_key
from app.services.extension_package import (
    CRX3_SIGNATURE_CONTEXT,
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

TEMPLATE = {
    "manifest_version": 3,
    "name": "Alpharouter",
    "version": "0.0.0",
    "permissions": ["sidePanel", "storage"],
    "host_permissions": [],
    "optional_host_permissions": ["<all_urls>"],
}


@pytest.fixture(scope="module")
def key() -> ExtensionKey:
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    der = private.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    return ExtensionKey(private_key=private, public_der=der)


class TestTheVersion:
    @pytest.mark.parametrize(
        ("app_version", "revision", "expected"),
        [
            ("v1.2.3", 0, "1.2.3.32768"),
            ("v1.2.3", 5, "1.2.3.32773"),
            ("1.2.3", 0, "1.2.3.32768"),
            ("v1.2", 0, "1.2.0.32768"),
            ("v7", 1, "7.0.0.32769"),
            # git describe after the tag, and a dirty tree: the tag's code or later.
            ("v1.2.0-5-gabc1234", 0, "1.2.0.32768"),
            ("v1.2.0-dirty", 2, "1.2.0.32770"),
            # A pre-release stays below the release of the same numbers.
            ("v1.3.0-rc.1", 2, "1.3.0.2"),
            ("v1.3.0-RC2", 0, "1.3.0.0"),
            ("v1.3.0-beta", 0, "1.3.0.0"),
            ("v1.3.0-preview.4", 0, "1.3.0.0"),
            # No version: below any real release.
            ("gabc1234", 3, "0.0.0.3"),
            ("", 0, "0.0.0.0"),
            (None, 0, "0.0.0.0"),
            ("v70000.1.1", 0, "65535.1.1.32768"),
            ("v01.002.3", 0, "1.2.3.32768"),
        ],
    )
    def test_it_follows_the_app_version(self, app_version, revision, expected):
        assert extension_version(app_version, revision) == expected

    @pytest.mark.parametrize("revision", [-1, 32768])
    def test_the_revision_has_room_below_the_release_offset(self, revision):
        with pytest.raises(ValueError):
            extension_version("v1.0.0", revision)

    def test_updates_move_forward(self):
        def as_tuple(v: str) -> tuple[int, ...]:
            return tuple(int(p) for p in v.split("."))

        sequence = [
            extension_version("", 0),
            extension_version("v1.2.0-rc.1", 0),
            extension_version("v1.2.0", 0),
            extension_version("v1.2.0", 1),
            extension_version("v1.2.1-rc.1", 5),
            extension_version("v1.2.1", 0),
        ]
        assert [as_tuple(v) for v in sequence] == sorted(as_tuple(v) for v in sequence)
        assert len(set(sequence)) == len(sequence)


class TestTheOrigin:
    @pytest.mark.parametrize(
        ("url", "origin"),
        [
            ("https://AI.Example.com/", "https://ai.example.com"),
            ("https://ai.example.com:443/app", "https://ai.example.com"),
            ("http://127.0.0.1:8080", "http://127.0.0.1:8080"),
            ("http://10.0.0.5:80/", "http://10.0.0.5"),
            ("https://ai.example.com:8443/x?y#z", "https://ai.example.com:8443"),
            ("http://[::1]:8080/", "http://[::1]:8080"),
        ],
    )
    def test_it_is_scheme_host_and_port(self, url, origin):
        assert normalize_origin(url) == origin

    @pytest.mark.parametrize(
        "url", ["", "ftp://x.example", "chrome-extension://abc", "https://", "https://u:p@x.example"]
    )
    def test_anything_else_is_refused(self, url):
        with pytest.raises(ValueError):
            normalize_origin(url)


class TestTheManifest:
    def _manifest(self, site_access: str) -> dict:
        return build_manifest(
            TEMPLATE,
            version="1.2.3.32768",
            version_name="v1.2.3",
            public_key_b64="S0VZ",
            origin="https://ai.example.com",
            site_access=site_access,
        )

    def test_it_is_this_servers_extension(self):
        manifest = self._manifest("per_site")
        assert manifest["key"] == "S0VZ"
        assert manifest["version"] == "1.2.3.32768"
        assert manifest["version_name"] == "v1.2.3"
        assert manifest["update_url"] == "https://ai.example.com/extension/update.xml"
        assert manifest["web_accessible_resources"] == [
            {"resources": ["connected.html"], "matches": ["https://ai.example.com/*"]}
        ]
        assert manifest["permissions"] == TEMPLATE["permissions"]

    def test_per_site_access_asks_for_each_site(self):
        manifest = self._manifest("per_site")
        assert manifest["host_permissions"] == ["https://ai.example.com/*"]
        assert manifest["optional_host_permissions"] == ["<all_urls>"]

    def test_all_sites_access_is_granted_at_install(self):
        manifest = self._manifest("all_sites")
        assert manifest["host_permissions"] == ["https://ai.example.com/*", "<all_urls>"]
        assert "optional_host_permissions" not in manifest

    def test_the_template_is_not_changed(self):
        before = json.dumps(TEMPLATE, sort_keys=True)
        self._manifest("all_sites")
        assert json.dumps(TEMPLATE, sort_keys=True) == before

    def test_an_unknown_mode_is_refused(self):
        with pytest.raises(ValueError):
            self._manifest("some_sites")


class TestTheZip:
    def _files(self) -> dict[str, bytes]:
        return package_files(
            {"manifest.json": b"{}", "background.js": b"sw", "assets/panel.js": b"p", "config.json": b"{}"},
            manifest={"manifest_version": 3, "name": "Alpharouter"},
            config=extension_config(origin="https://ai.example.com", server_name="Alpharouter", version="1.0.0.0"),
        )

    def test_files_sit_at_the_root_in_order_with_this_servers_manifest(self):
        archive = zipfile.ZipFile(io.BytesIO(build_zip(self._files())))
        assert archive.namelist() == ["assets/panel.js", "background.js", "config.json", "manifest.json"]
        assert json.loads(archive.read("manifest.json")) == {"manifest_version": 3, "name": "Alpharouter"}
        assert json.loads(archive.read("config.json")) == {
            "serverUrl": "https://ai.example.com",
            "serverName": "Alpharouter",
            "extensionVersion": "1.0.0.0",
        }
        assert all(info.date_time == (1980, 1, 1, 0, 0, 0) for info in archive.infolist())

    def test_it_is_reproducible(self):
        assert build_zip(self._files()) == build_zip(dict(reversed(list(self._files().items()))))

    def test_a_built_folder_is_read_whole(self, tmp_path):
        (tmp_path / "assets").mkdir()
        (tmp_path / "manifest.json").write_text(json.dumps(TEMPLATE))
        (tmp_path / "assets" / "panel.js").write_bytes(b"p")
        files = read_dist(tmp_path)
        assert sorted(files) == ["assets/panel.js", "manifest.json"]
        assert load_template(files)["name"] == "Alpharouter"

    def test_a_folder_without_a_build_is_refused(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            read_dist(tmp_path)

    def test_a_manifest_that_is_not_v3_is_refused(self):
        with pytest.raises(ValueError):
            load_template({"manifest.json": b'{"manifest_version": 2}'})


def _read_varint(data: bytes, pos: int) -> tuple[int, int]:
    shift = value = 0
    while True:
        byte = data[pos]
        pos += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, pos
        shift += 7


def _fields(data: bytes) -> dict[int, list[bytes]]:
    """A minimal protobuf reader: length-delimited fields only, which is all a CRX3 header holds."""
    out: dict[int, list[bytes]] = {}
    pos = 0
    while pos < len(data):
        tag, pos = _read_varint(data, pos)
        assert tag & 0x07 == 2, "only length-delimited fields are expected"
        length, pos = _read_varint(data, pos)
        out.setdefault(tag >> 3, []).append(data[pos : pos + length])
        pos += length
    return out


class TestTheCrx:
    def test_it_is_a_crx3_signed_by_this_installation(self, key):
        archive = build_zip({"manifest.json": b'{"manifest_version": 3}'})
        crx = build_crx3(archive, key)

        assert crx[:4] == b"Cr24"
        assert struct.unpack("<I", crx[4:8])[0] == 3
        header_size = struct.unpack("<I", crx[8:12])[0]
        header = crx[12 : 12 + header_size]
        assert crx[12 + header_size :] == archive

        fields = _fields(header)
        assert list(fields) == [2, 10000]
        proof = _fields(fields[2][0])
        public_der, signature = proof[1][0], proof[2][0]
        signed_data = fields[10000][0]
        crx_id = _fields(signed_data)[1][0]

        assert public_der == key.public_der
        assert crx_id == hashlib.sha256(public_der).digest()[:16]
        assert extension_id_from_public_key(public_der) == key.extension_id
        # Raises InvalidSignature if anything above were wrong.
        serialization.load_der_public_key(public_der).verify(
            signature,
            CRX3_SIGNATURE_CONTEXT + struct.pack("<I", len(signed_data)) + signed_data + archive,
            padding.PKCS1v15(),
            hashes.SHA256(),
        )


#: A CRX that Chromium 141 packed itself (chrome --pack-extension) from a
#: one-line manifest, and the throwaway key it made for it. Nothing signs
#: anything real with this key; it only pins the format.
_CHROMIUM_CRX_B64 = (
    "Q3IyNAMAAABFAgAAEqwECqYCMIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA08Tk5TR93ko8tgVKaZ8V6+L3mbY8jIHv"
    "hmmnQXz3W59rkV0GBWeZ2Ddz7fa/SD2+JhVlOYCQyIgjoFuspJa0Rcg5n50Ypxkh0x1gU3niIJG708woJG8V9lIgNEqH9lPB+yKs"
    "lYLrEaRwfuaZOIxJDSUdJbOwFO8scEyr9APGxpv22NLFa8ptKAHswaGEv4b91wu6nbIFhsXSgBNZqbdHI1B0ks2TdKwp94CLhkor"
    "6oQ7zKOuBkaBebDWK/T+ORBQ+YJaF/aG/hMH+EgI4cT+T7t6PHHsnpVqh7ZE1kYIixeJyPBCQj7pv+TmSWHdWSq8G8iMDEdcY8Ny"
    "PCLFQ8GcMwIDAQABEoAC0YLC8hgQQrsuzXDosBEADcpf99YzH2Obr/xeX49R4mdV9wayoZDRX2KlpzMjVgOD8INt4IHcY3OL12sd"
    "JwH8qOFhW0poDXqmehgekYbFCHeCzKMQElLx6/aThjUPpsHH88W70qll/ad2PEGLrf5WjfRf1VQ8+xi6ViUHdogQ+n6VFjLH4qpq"
    "i0aReBFiEyywCWtGz5xHuBoR4Nx0A2UOBRF7zsACUcCrTkH9R7FexC7oE3x+I2qciseRxAT8mX7pxpnngdvDpufZTIn+OW4d9yaM"
    "OC4t+XHm0+vhNVgKgQeV12I5+fcq36BHCWxYaVo6rn3bjWVK3qquJrzyFZqoiYLxBBIKEC6KoCa61TXB/TwPHDNwWBxQSwMELQAA"
    "CAgAErU4Xa2BU2ExAAAANwAAAA0AFABtYW5pZmVzdC5qc29uAQAQAAAAAAAAAAAAAAAAAAAAAACrVspNzMtMSy0uiS9LLSrOzM9T"
    "slIw1lFQykvMTVWyUlAqUdJRUEJIKRnqGSjVcgEAUEsBAgAAFAAACAgAErU4Xa2BU2ExAAAANwAAAA0AAAAAAAAAAQAAAAAAAAAA"
    "AG1hbmlmZXN0Lmpzb25QSwUGAAAAAAEAAQA7AAAAcAAAAAAA"
)

_CHROMIUM_KEY_DER_B64 = (
    "MIIEvgIBADANBgkqhkiG9w0BAQEFAASCBKgwggSkAgEAAoIBAQDTxOTlNH3eSjy2BUppnxXr4veZtjyMge+GaadBfPdbn2uRXQYF"
    "Z5nYN3Pt9r9IPb4mFWU5gJDIiCOgW6yklrRFyDmfnRinGSHTHWBTeeIgkbvTzCgkbxX2UiA0Sof2U8H7IqyVgusRpHB+5pk4jEkN"
    "JR0ls7AU7yxwTKv0A8bGm/bY0sVrym0oAezBoYS/hv3XC7qdsgWGxdKAE1mpt0cjUHSSzZN0rCn3gIuGSivqhDvMo64GRoF5sNYr"
    "9P45EFD5gloX9ob+Ewf4SAjhxP5Pu3o8ceyelWqHtkTWRgiLF4nI8EJCPum/5OZJYd1ZKrwbyIwMR1xjw3I8IsVDwZwzAgMBAAEC"
    "ggEAGwLKVqk52WsVpaU0xxZpXjjeb7GMtTfzkcI9zlQUBuXle1k7+zTU130ci9XaXcAGVhGKOOnlowuo+Ptdy3EvgEEYMdGArfuT"
    "fWaJ/UvBZHnCKoh9TEcLrECbEUsPtC3IbccP7/1kDKWGoHZlmmQGWKdgZDPa+eiXKKHBmF0M8xMA9jY7BMQs/r8J1dAyu/0HFR+v"
    "ApXpmgPo26l/ZXVtLrnRBLZz9dLttV+s/YOZwNtekFcZYhLzkSVcJtQWCdRcc32KZSVO52QO7PFSeSrIDFGOmC4jKuLDDm22rp/k"
    "aCkmFrKnPjSKU96ruX3nckfKPJobqyW89V5OCtzrMJn73QKBgQD/+Rf09A6Ujr1qXnJtCpoTAJRXInQzQIFTTtdD8AVzyg5aw+XH"
    "7r4VF7ULdhXFDezQ0B2jJIQWyMzY/MZOVG0tQYtdH/BR8RSGsYqH72NGhilaj3ucBchp0mK1KlHvmMWwiEMGF/eacGl7UX1E8pnF"
    "JmNerUAXHfDsN1/e9+fRVQKBgQDTypudmsxyc4GBwQNVQeUR7l29uahhcuiJ7Jkgit6GDSuWycgflzdV8Cb580loUqHMEQmTTl23"
    "nPDKl04vFjESr3dy0EBaPSH//Mx01wvQKXB4Lg4VpJanvzMoESQ75fnixYK2xEc41uvmm2A0fvzUqrsg3kx+zHUW1ESJ+fbXZwKB"
    "gQD3ZVvHLv7MjCz8Gm6DfySsyvmUQcOHKYgU6XVavye14or/JKj4FIH4xuH/QtEFlFDW/N44KHnVv5tk+OH9INIoVFoK1myh9dx9"
    "1ihq+2664b4kPdsdT+WEiYdHS7DHXqNq3DfTMuTnilAYlQj603LVPiX6gn4YGaMZ2uc5C+csxQKBgDY64d/YPFNuChI8ZusUxV/z"
    "BiPHfzr8nlh6sbboeBQhGTEyF8EnCi9CH+jOh9RjnDRRhH8oiMy0Ld/iIE3kQ8qCDXbjpia1EpimlX+xdL/nbHoJaOfXzg/D4Ih4"
    "4ytHNtX/NvovhgEi3yKcVGT8wyZ9VQ8UfMfW+IBQ9//QdokvAoGBALtormi5riOCGblAKGV6IO+8dSF/UIhjr0os/hQwA1o0nZyW"
    "c6mMKPU6uhYxqMpE/Gn6cxf8IL6P0lqizEoodgFBi0OYF5lRSlVDi0xPUJoasFpjoyRX4exNNy2uuZO+QXRC4ubUYLIpA6n3KsGW"
    "dAzwYAY6OETgtnCgT/EbcPDK"
)


class TestTheCrxIsWhatChromiumWrites:
    def test_the_same_archive_and_key_give_the_same_bytes(self):
        """Byte for byte: header layout, field numbers, what is signed and how."""
        packed = base64.b64decode("".join(_CHROMIUM_CRX_B64))
        private = serialization.load_der_private_key(base64.b64decode("".join(_CHROMIUM_KEY_DER_B64)), password=None)
        der = private.public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
        )
        header_size = struct.unpack("<I", packed[8:12])[0]
        archive = packed[12 + header_size :]
        assert build_crx3(archive, ExtensionKey(private_key=private, public_der=der)) == packed


class TestTheUpdateManifest:
    def test_it_points_at_this_version_of_this_extension(self):
        xml = update_manifest_xml(
            extension_id="abcdefghijklmnopabcdefghijklmnop",
            codebase=crx_url("https://ai.example.com", "1.2.3.32768"),
            version="1.2.3.32768",
        )
        root = ElementTree.fromstring(xml)
        ns = "{http://www.google.com/update2/response}"
        assert root.tag == f"{ns}gupdate" and root.get("protocol") == "2.0"
        app = root.find(f"{ns}app")
        assert app.get("appid") == "abcdefghijklmnopabcdefghijklmnop"
        check = app.find(f"{ns}updatecheck")
        assert check.get("codebase") == "https://ai.example.com/extension/alpharouter.crx?v=1.2.3.32768"
        assert check.get("version") == "1.2.3.32768"

    def test_values_are_escaped(self):
        xml = update_manifest_xml(extension_id="a", codebase="https://x.example/c?a=1&b='2'", version="1")
        check = ElementTree.fromstring(xml).find(".//{http://www.google.com/update2/response}updatecheck")
        assert check.get("codebase") == "https://x.example/c?a=1&b='2'"

    def test_the_update_url_is_on_the_server(self):
        assert update_url("https://ai.example.com") == "https://ai.example.com/extension/update.xml"
