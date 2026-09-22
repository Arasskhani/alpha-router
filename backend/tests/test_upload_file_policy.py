"""The operator-owned upload policy, and the two protections that sit outside it.

``upload_file_policy`` replaced two hard-coded lists with one policy an
administrator edits, so the things that used to be guaranteed by the code
now have to be guaranteed by tests: that a name is judged on *every* suffix,
that the allowlist is a narrowing on top of the blocklist and never a way
around it, that the bytes of an executable are refused whatever the operator
removed from the list, that HTML/SVG never hides behind an inline kind, that
what the operator saves is what the next upload sees, and that the per-process
cache forgets exactly when it should.
"""

from __future__ import annotations

import json
import time
from dataclasses import FrozenInstanceError

import pytest

from app.models.system import SystemSetting
from app.services import attachment_policy as legacy
from app.services import upload_file_policy as module
from app.services.upload_file_policy import (
    DEFAULT_ALLOWED,
    DEFAULT_BLOCKED,
    DEFAULT_POLICY,
    KEY_ALLOWED,
    KEY_BLOCKED,
    KEY_MODE,
    MAX_LIST_ENTRIES,
    Policy,
    UploadPolicyError,
    check_content,
    check_upload,
    classify,
    classify_name,
    invalidate_policy_cache,
    kind_for_extension,
    load_policy,
    normalize_extension,
    normalize_extension_list,
    normalize_mode,
    reset_policy,
    save_policy,
)

PNG_HEADER = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + b"\x00" * 16
JPEG_HEADER = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00" + b"\x00" * 16
GIF_HEADER = b"GIF89a" + b"\x01\x00\x01\x00" + b"\x00" * 16
WEBP_HEADER = b"RIFF\x24\x00\x00\x00WEBPVP8 " + b"\x00" * 16
BMP_HEADER = b"BM" + b"\x36\x00\x00\x00" + b"\x00" * 16
TIFF_LE_HEADER = b"II*\x00" + b"\x08\x00\x00\x00" + b"\x00" * 16
TIFF_BE_HEADER = b"MM\x00*" + b"\x00\x00\x00\x08" + b"\x00" * 16

SVG_BYTES = b"<svg xmlns='http://www.w3.org/2000/svg' onload='alert(1)'></svg>"
BOM_HTML_BYTES = b"\xef\xbb\xbf  <!DOCTYPE html><html><body>hi</body></html>"
XML_SVG_BYTES = b"<?xml version='1.0'?><svg xmlns='http://www.w3.org/2000/svg'/>"
SCRIPT_BYTES = b"<script>alert(1)</script>"


@pytest.fixture(autouse=True)
def _fresh_policy_cache():
    """The policy cache is module-level state; no test may inherit another's."""

    invalidate_policy_cache()
    yield
    invalidate_policy_cache()


def _refusal(fn, *args, **kwargs) -> str:
    """Call ``fn`` expecting ``UploadPolicyError``; return the message shown to the person."""

    with pytest.raises(UploadPolicyError) as exc:
        fn(*args, **kwargs)
    return str(exc.value)


# --------------------------------------------------------------------------- #
# Normalisation of what an operator types
# --------------------------------------------------------------------------- #


class TestNormalizeExtension:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            (".PDF ", "pdf"),
            ("pdf", "pdf"),
            ("  .Png", "png"),
            ("..gz", "gz"),
            ("7z", "7z"),
            ("a" * 16, "a" * 16),
        ],
    )
    def test_a_plain_extension_is_lowercased_and_stripped_of_its_dot(self, raw, expected):
        assert normalize_extension(raw) == expected

    @pytest.mark.parametrize(
        "raw",
        [
            "",
            ".",
            " ",
            "tar.gz",
            "a b",
            "exe;",
            "a" * 17,
            "pdf\u00e9",
            "\uff30\uff24\uff26",
            "\u0661\u0662\u0663",
            "exe/",
            "*",
        ],
    )
    def test_anything_that_is_not_a_plain_extension_is_refused(self, raw):
        """Compound suffixes, separators, punctuation, overlong and non-ASCII
        entries are all None: the operator is told, not silently trimmed."""
        assert normalize_extension(raw) is None

    def test_none_is_treated_as_empty(self):
        assert normalize_extension(None) is None  # type: ignore[arg-type]


class TestNormalizeExtensionList:
    def test_accepted_entries_are_deduplicated_and_sorted(self):
        accepted, rejected = normalize_extension_list(["PNG", ".png", "pdf", "Pdf ", "exe"])
        assert accepted == ["exe", "pdf", "png"]
        assert rejected == []

    def test_rejected_entries_come_back_verbatim_and_in_order(self):
        """The error the operator sees must quote what they typed, not a
        cleaned-up version they will not recognise."""
        accepted, rejected = normalize_extension_list(["pdf", "tar.gz", "", " a b ", ".PNG"])
        assert accepted == ["pdf", "png"]
        assert rejected == ["tar.gz", "", " a b "]

    def test_a_frozenset_and_a_tuple_are_accepted_as_input(self):
        assert normalize_extension_list(frozenset({"b", "a"})) == (["a", "b"], [])
        assert normalize_extension_list(("b", "a", "b")) == (["a", "b"], [])

    def test_an_empty_list_is_empty(self):
        assert normalize_extension_list([]) == ([], [])


class TestNormalizeMode:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            (None, "blocklist"),
            ("", "blocklist"),
            ("blocklist", "blocklist"),
            ("allowlist", "allowlist"),
            (" ALLOWLIST ", "allowlist"),
            ("denylist", "blocklist"),
            ("whitelist", "blocklist"),
        ],
    )
    def test_unknown_modes_fall_back_to_the_blocklist(self, raw, expected):
        """A corrupt or unknown stored mode must fail *open* on the lists
        (blocklist mode accepts more) rather than lock every upload out; the
        fixed content check is unaffected either way."""
        assert normalize_mode(raw) == expected


# --------------------------------------------------------------------------- #
# Deciding about a name
# --------------------------------------------------------------------------- #


class TestPolicyDataclass:
    def test_the_default_policy_is_the_lists_the_code_used_to_hard_code(self):
        assert DEFAULT_POLICY.mode == "blocklist"
        assert DEFAULT_POLICY.blocked == legacy.BLOCKED_EXTENSIONS
        assert DEFAULT_POLICY.allowed == legacy.ALLOWED_EXTENSIONS
        assert "exe" in DEFAULT_BLOCKED and "svg" in DEFAULT_BLOCKED and "zip" in DEFAULT_BLOCKED
        assert "pdf" in DEFAULT_ALLOWED and "psd" not in DEFAULT_ALLOWED

    def test_a_policy_is_immutable(self):
        """The cached instance is handed to every upload; nothing may mutate it."""
        with pytest.raises(FrozenInstanceError):
            DEFAULT_POLICY.mode = "allowlist"  # type: ignore[misc]

    def test_as_dict_is_sorted_and_carries_the_defaults_for_restore(self):
        policy = Policy(mode="allowlist", blocked=frozenset({"zip", "exe"}), allowed=frozenset({"png", "pdf"}))
        data = policy.as_dict()
        assert data == {
            "mode": "allowlist",
            "blocked": ["exe", "zip"],
            "allowed": ["pdf", "png"],
            "default_blocked": sorted(DEFAULT_BLOCKED),
            "default_allowed": sorted(DEFAULT_ALLOWED),
        }


class TestKindForExtension:
    @pytest.mark.parametrize(
        "ext,kind",
        [
            ("png", "image"),
            ("heic", "image"),
            ("mkv", "video"),
            ("mp3", "audio"),
            ("pdf", "document"),
            ("json", "document"),
            ("psd", "file"),
            ("parquet", "file"),
            ("exe", "file"),
        ],
    )
    def test_known_kinds_and_the_file_fallback(self, ext, kind):
        assert kind_for_extension(ext) == kind


class TestClassifyDefaultPolicy:
    @pytest.mark.parametrize(
        "filename,expected",
        [
            ("report.pdf", ("pdf", "document")),
            ("photo.JPG", ("jpg", "image")),
            ("clip.mkv", ("mkv", "video")),
            ("talk.mp3", ("mp3", "audio")),
            ("design.psd", ("psd", "file")),
            ("data.parquet", ("parquet", "file")),
            ("notes.backup.txt", ("txt", "document")),
            (".hidden.txt", ("txt", "document")),
        ],
    )
    def test_extension_and_kind(self, filename, expected):
        """``.psd`` and ``.parquet`` are the whole point of the change: they
        used to be refused as "not supported"; now they are ``file``."""
        assert classify(filename) == expected

    @pytest.mark.parametrize(
        "filename,blocked_ext",
        [
            ("report.pdf.exe", "exe"),
            ("photo.exe.jpg", "exe"),
            ("archive.tar.gz", "tar"),
            ("run.sh", "sh"),
            ("page.html", "html"),
            ("logo.svg", "svg"),
            ("LOADER.EXE", "exe"),
        ],
    )
    def test_every_suffix_is_checked_against_the_blocklist(self, filename, blocked_ext):
        """``photo.exe.jpg`` is a name chosen to get past a check that reads
        one suffix; ``archive.tar.gz`` is refused on its first blocked suffix."""
        message = _refusal(classify, filename)
        assert f'".{blocked_ext}"' in message
        assert "not allowed on this platform" in message

    @pytest.mark.parametrize("filename", ["README", ".bashrc", "Makefile", "file."])
    def test_a_name_without_an_extension_is_refused(self, filename):
        """``.bashrc`` has no suffix in ``PurePath`` terms (the leading dot is
        the name), so it must be refused as extension-less, not accepted as
        ``bashrc``."""
        assert _refusal(classify, filename) == "Files must have an extension."

    @pytest.mark.parametrize("filename", ["", "   ", "\t\n", None])
    def test_a_missing_name_is_refused(self, filename):
        assert _refusal(classify, filename) == "Missing file name."

    @pytest.mark.parametrize(
        "filename,expected",
        [
            ("C:\\Users\\x\\a.pdf", ("pdf", "document")),
            ("C:\\Users\\x.exe\\a.pdf", ("pdf", "document")),
            ("/tmp/uploads.exe/photo.jpg", ("jpg", "image")),
            ("my.folder/data.parquet", ("parquet", "file")),
            ("  spaced.png  ", ("png", "image")),
        ],
    )
    def test_directories_and_windows_separators_are_stripped(self, filename, expected):
        """Only the file's own name decides; a dot in a directory name is not a suffix."""
        assert classify(filename) == expected

    def test_a_directory_with_no_file_is_extension_less(self):
        assert _refusal(classify, "my.folder/README") == "Files must have an extension."


class TestClassifyAllowlistMode:
    POLICY = Policy(mode="allowlist", allowed=frozenset({"pdf", "png"}))

    def test_a_listed_extension_passes(self):
        assert classify("a.pdf", self.POLICY) == ("pdf", "document")
        assert classify("A.PNG", self.POLICY) == ("png", "image")

    def test_an_unlisted_extension_is_refused_with_the_allowlist_message(self):
        message = _refusal(classify, "a.psd", self.POLICY)
        assert message == 'File type ".psd" is not on the list of allowed file types.'

    def test_the_allowlist_reads_the_last_suffix_only(self):
        """``notes.backup.pdf`` is a PDF; the allowlist judges what the file *is*."""
        assert classify("notes.backup.pdf", self.POLICY) == ("pdf", "document")

    def test_the_blocklist_still_applies_and_is_checked_first(self):
        """Putting ``exe`` on the allowed list does not let an executable in
        while ``exe`` is also blocked: the blocklist wins, and the message is
        the blocklist's, not the allowlist's."""
        policy = Policy(mode="allowlist", allowed=frozenset({"pdf", "exe"}))
        message = _refusal(classify, "a.exe", policy)
        assert message == 'File type ".exe" is not allowed on this platform.'
        assert "allowed file types" not in message

    def test_a_blocked_inner_suffix_is_refused_even_when_the_outer_one_is_allowed(self):
        message = _refusal(classify, "photo.exe.png", self.POLICY)
        assert '".exe"' in message and "not allowed on this platform" in message

    def test_an_extension_less_name_is_still_extension_less(self):
        assert _refusal(classify, "README", self.POLICY) == "Files must have an extension."


class TestClassifyOperatorEditedBlocklist:
    def test_removing_exe_from_the_blocklist_accepts_the_name(self):
        """There is no locked core: the operator may unblock anything by name.
        What still stops a real executable is ``check_content`` (below)."""
        policy = Policy(blocked=DEFAULT_BLOCKED - {"exe"})
        assert classify("tool.exe", policy) == ("exe", "file")

    def test_unblocking_by_name_does_not_unblock_the_bytes(self):
        policy = Policy(blocked=DEFAULT_BLOCKED - {"exe"})
        ext, kind = classify("tool.exe", policy)
        message = _refusal(check_content, b"MZ\x90\x00\x03\x00\x00\x00", ext=ext, kind=kind)
        assert message == '"exe" file rejected: its contents are a Windows executable.'

    def test_the_operator_may_block_a_default_document_type(self):
        policy = Policy(blocked=frozenset({"pdf"}))
        message = _refusal(classify, "a.pdf", policy)
        assert message == 'File type ".pdf" is not allowed on this platform.'
        # ...and with that policy the default blocklist is gone entirely.
        assert classify("tool.exe", policy) == ("exe", "file")

    def test_an_empty_blocklist_accepts_everything_with_a_suffix(self):
        policy = Policy(blocked=frozenset())
        assert classify("archive.tar.gz", policy) == ("gz", "file")


class TestErrorClass:
    def test_upload_policy_error_is_an_attachment_policy_error(self):
        """Callers that catch the old class keep working after the switch."""
        assert issubclass(UploadPolicyError, legacy.AttachmentPolicyError)
        assert issubclass(UploadPolicyError, ValueError)

    def test_the_old_except_clause_catches_the_new_error(self):
        with pytest.raises(legacy.AttachmentPolicyError):
            classify("virus.exe")


# --------------------------------------------------------------------------- #
# Deciding about the bytes (not configurable)
# --------------------------------------------------------------------------- #


class TestCheckContentExecutables:
    @pytest.mark.parametrize(
        "raw,ext,kind,what",
        [
            (b"MZ\x90\x00\x03\x00\x00\x00\x04\x00", "dat", "file", "a Windows executable"),
            (b"\x7fELF\x02\x01\x01\x00", "txt", "document", "a Linux executable"),
            (b"\xfe\xed\xfa\xce\x00\x00\x00\x12", "blob", "file", "a macOS executable"),
            (b"\xfe\xed\xfa\xcf\x00\x00\x00\x12", "blob", "file", "a macOS executable"),
            (b"\xce\xfa\xed\xfe\x07\x00\x00\x01", "blob", "file", "a macOS executable"),
            (b"\xcf\xfa\xed\xfe\x07\x00\x00\x01", "blob", "file", "a macOS executable"),
            (b"\xca\xfe\xba\xbe\x00\x00\x00\x34", "data", "file", "a Java class or macOS universal binary"),
        ],
    )
    def test_an_executable_is_refused_under_any_name_and_kind(self, raw, ext, kind, what):
        """These names are not blocked by any list; the bytes alone decide."""
        assert normalize_extension(ext) not in DEFAULT_BLOCKED
        message = _refusal(check_content, raw, ext=ext, kind=kind)
        assert message == f'"{ext}" file rejected: its contents are {what}.'

    @pytest.mark.parametrize("kind", ["image", "video", "audio", "document", "file"])
    def test_the_executable_check_runs_for_every_kind(self, kind):
        message = _refusal(check_content, b"MZ" + b"\x00" * 62, ext="x", kind=kind)
        assert "a Windows executable" in message

    def test_a_pe_signature_wins_over_the_image_check(self):
        """An ``MZ`` file named ``.png`` is reported as an executable, not
        merely as "not an image": the person (and the log) should see what it was."""
        message = _refusal(check_content, b"MZ" + b"\x00" * 62, ext="png", kind="image")
        assert "a Windows executable" in message


class TestCheckContentMarkupBehindInlineKinds:
    @pytest.mark.parametrize(
        "raw,ext,kind",
        [
            (SVG_BYTES, "png", "image"),
            (BOM_HTML_BYTES, "jpg", "image"),
            (XML_SVG_BYTES, "gif", "image"),
            (SCRIPT_BYTES, "mp4", "video"),
            (SCRIPT_BYTES, "mp3", "audio"),
            (b"\n\t  <HTML><BODY>x</BODY></HTML>", "webp", "image"),
            (b"\xff\xfe<svg/>", "bmp", "image"),
        ],
    )
    def test_html_or_svg_behind_an_inline_kind_is_refused(self, raw, ext, kind):
        """An ``<svg onload>`` served as ``image/png`` is the XSS this product
        must never offer; BOMs, whitespace, XML prologues and upper case must
        not get it past the check."""
        message = _refusal(check_content, raw, ext=ext, kind=kind)
        assert message == f'"{ext}" file rejected: its contents are HTML or SVG, not {kind}.'

    @pytest.mark.parametrize("raw", [SVG_BYTES, BOM_HTML_BYTES, XML_SVG_BYTES, SCRIPT_BYTES])
    @pytest.mark.parametrize("ext,kind", [("txt", "document"), ("xyz", "file")])
    def test_the_same_bytes_pass_as_a_document_or_a_file(self, raw, ext, kind):
        """Documents and unknown files are always served as downloads, so
        their bytes may be anything that is not an executable."""
        assert check_content(raw, ext=ext, kind=kind) is None

    def test_text_that_merely_starts_with_an_angle_bracket_is_not_markup(self):
        """``_looks_like_markup`` needs one of the markers, not just ``<``;
        such text is still refused as an image, by the text check, with the
        image message."""
        message = _refusal(check_content, b"<notes>plain</notes>", ext="png", kind="image")
        assert message == '"png" file rejected: its contents are not an image.'


class TestCheckContentImages:
    @pytest.mark.parametrize(
        "raw,ext",
        [
            (PNG_HEADER, "png"),
            (JPEG_HEADER, "jpg"),
            (JPEG_HEADER, "jpeg"),
            (GIF_HEADER, "gif"),
            (WEBP_HEADER, "webp"),
            (BMP_HEADER, "bmp"),
            (TIFF_LE_HEADER, "tif"),
            (TIFF_BE_HEADER, "tiff"),
        ],
    )
    def test_real_image_signatures_pass(self, raw, ext):
        assert check_content(raw, ext=ext, kind="image") is None

    def test_a_real_image_under_the_wrong_image_extension_still_passes(self):
        """The check is "is this an image", not "is this exactly a PNG": a
        JPEG named ``.png`` is served as an image type either way."""
        assert check_content(JPEG_HEADER, ext="png", kind="image") is None

    @pytest.mark.parametrize("ext", ["png", "jpg", "gif", "webp", "heic", "avif"])
    def test_plain_text_pretending_to_be_an_image_is_refused(self, ext):
        message = _refusal(check_content, b"hello, I am definitely a picture\n", ext=ext, kind="image")
        assert message == f'"{ext}" file rejected: its contents are not an image.'

    @pytest.mark.parametrize(
        "raw",
        [
            bytes(range(0, 64)),  # contains NUL: binary
            b"\x80\x81\xfe\xff\x00\x00\x00\x18",  # not valid UTF-8
            b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00",  # a real HEIC brand box
        ],
    )
    def test_binary_the_product_does_not_sniff_passes_as_an_image(self, raw):
        """HEIC variants and exotic formats are not sniffed; only *text*
        pretending to be a picture is refused."""
        assert check_content(raw, ext="heic", kind="image") is None

    def test_ico_is_exempt_from_the_text_check(self):
        """Explicitly exempt in the module: no signature is sniffed for it."""
        assert check_content(b"just some text in an icon file", ext="ico", kind="image") is None

    def test_ico_is_not_exempt_from_the_markup_or_executable_checks(self):
        assert "HTML or SVG" in _refusal(check_content, SVG_BYTES, ext="ico", kind="image")
        assert "Windows executable" in _refusal(check_content, b"MZ\x00\x00", ext="ico", kind="image")

    def test_text_is_fine_for_non_image_kinds(self):
        assert check_content(b"plain text", ext="txt", kind="document") is None
        assert check_content(b"plain text", ext="xyz", kind="file") is None
        assert check_content(b"plain text", ext="mp3", kind="audio") is None
        assert check_content(b"plain text", ext="mp4", kind="video") is None


class TestCheckContentEdges:
    @pytest.mark.parametrize("kind", ["image", "video", "audio", "document", "file"])
    def test_an_empty_file_is_refused(self, kind):
        assert _refusal(check_content, b"", ext="png", kind=kind) == "Empty file."

    def test_only_the_first_bytes_are_read(self):
        """A 10 MB upload with ``MZ`` at offset 5000 and a real PNG header at
        the front is a PNG: the sniff window is 4096 bytes, and the check must
        not scan the whole body (every upload goes through it)."""
        body = bytearray(10 * 1024 * 1024)
        body[: len(PNG_HEADER)] = PNG_HEADER
        body[5000:5002] = b"MZ"
        body[6000 : 6000 + len(SVG_BYTES)] = SVG_BYTES
        raw = bytes(body)

        started = time.perf_counter()
        assert check_content(raw, ext="png", kind="image") is None
        assert time.perf_counter() - started < 0.5

    def test_a_marker_inside_the_sniff_window_is_still_seen(self):
        """The window is 4096 bytes, not 4: whitespace padding before the markup
        does not hide it."""
        raw = b" " * 3000 + SVG_BYTES
        assert "HTML or SVG" in _refusal(check_content, raw, ext="png", kind="image")

    def test_a_bytearray_and_a_memoryview_are_accepted(self):
        assert check_content(bytearray(PNG_HEADER), ext="png", kind="image") is None
        assert check_content(memoryview(PNG_HEADER), ext="png", kind="image") is None  # type: ignore[arg-type]
        assert "Windows executable" in _refusal(check_content, bytearray(b"MZ\x00\x00"), ext="dat", kind="file")


# --------------------------------------------------------------------------- #
# Loading, saving and the cache
# --------------------------------------------------------------------------- #


async def _set_row(db, key: str, value: str | None) -> None:
    row = await db.get(SystemSetting, key)
    if row is None:
        db.add(SystemSetting(key=key, value=value))
    else:
        row.value = value
    await db.flush()


class TestLoadPolicy:
    async def test_nothing_saved_means_the_defaults(self, db_session):
        policy = await load_policy(db_session)
        assert policy == DEFAULT_POLICY
        assert policy.mode == "blocklist"
        assert policy.blocked == DEFAULT_BLOCKED
        assert policy.allowed == DEFAULT_ALLOWED

    async def test_a_saved_mode_and_lists_are_read_back(self, db_session):
        await _set_row(db_session, KEY_MODE, "allowlist")
        await _set_row(db_session, KEY_BLOCKED, json.dumps(["exe", "bat"]))
        await _set_row(db_session, KEY_ALLOWED, json.dumps(["pdf"]))

        policy = await load_policy(db_session, use_cache=False)
        assert policy == Policy(mode="allowlist", blocked=frozenset({"exe", "bat"}), allowed=frozenset({"pdf"}))

    @pytest.mark.parametrize("raw", ["{not json", "", "null", '{"a": 1}', "42", '"exe"'])
    async def test_an_unreadable_list_falls_back_to_the_default_for_that_list(self, db_session, raw):
        """A corrupt row must never take uploads down with an exception, and
        must not be read as "no restrictions" either."""
        await _set_row(db_session, KEY_BLOCKED, raw)
        await _set_row(db_session, KEY_ALLOWED, json.dumps(["pdf"]))

        policy = await load_policy(db_session, use_cache=False)
        assert policy.blocked == DEFAULT_BLOCKED
        assert policy.allowed == frozenset({"pdf"}), "the readable list next to it is still honoured"

    async def test_a_stored_list_is_normalised_and_bad_entries_dropped(self, db_session):
        """Rows written by an older build or by hand may hold anything. Only
        strings can be extensions: a number or a null in the list is dropped,
        not turned into a nonsense extension; compound or spaced entries are
        dropped too."""
        await _set_row(db_session, KEY_BLOCKED, json.dumps(["EXE", ".bat", "tar.gz", "a b", 7, None, True]))

        policy = await load_policy(db_session, use_cache=False)
        assert policy.blocked == frozenset({"exe", "bat"})

    async def test_an_unknown_stored_mode_is_the_blocklist(self, db_session):
        await _set_row(db_session, KEY_MODE, "denylist")
        assert (await load_policy(db_session, use_cache=False)).mode == "blocklist"

    async def test_a_null_value_in_a_row_is_the_default(self, db_session):
        await _set_row(db_session, KEY_BLOCKED, None)
        await _set_row(db_session, KEY_MODE, None)
        policy = await load_policy(db_session, use_cache=False)
        assert policy.blocked == DEFAULT_BLOCKED
        assert policy.mode == "blocklist"


class TestSavePolicy:
    async def test_saved_json_lands_in_system_settings_under_the_three_keys(self, db_session):
        returned = await save_policy(
            db_session, mode="allowlist", blocked=[".EXE", "exe", "Bat "], allowed=["PDF", "png", ".png"]
        )
        await db_session.commit()
        db_session.expire_all()

        mode_row = await db_session.get(SystemSetting, KEY_MODE)
        blocked_row = await db_session.get(SystemSetting, KEY_BLOCKED)
        allowed_row = await db_session.get(SystemSetting, KEY_ALLOWED)
        assert mode_row is not None and mode_row.value == "allowlist"
        assert blocked_row is not None and json.loads(blocked_row.value) == ["bat", "exe"]
        assert allowed_row is not None and json.loads(allowed_row.value) == ["pdf", "png"]

        assert returned == Policy(
            mode="allowlist", blocked=frozenset({"bat", "exe"}), allowed=frozenset({"pdf", "png"})
        )
        assert await load_policy(db_session, use_cache=False) == returned

    async def test_saving_twice_updates_the_rows_in_place(self, db_session):
        """Three rows, always: a second save must not fail on the primary key
        or leave the first save's rows behind."""
        await save_policy(db_session, mode="blocklist", blocked=["exe"], allowed=["pdf"])
        await save_policy(db_session, mode="allowlist", blocked=["zip"], allowed=["png"])

        blocked_row = await db_session.get(SystemSetting, KEY_BLOCKED)
        assert json.loads(blocked_row.value) == ["zip"]
        assert (await load_policy(db_session, use_cache=False)) == Policy(
            mode="allowlist", blocked=frozenset({"zip"}), allowed=frozenset({"png"})
        )

    async def test_empty_lists_are_a_valid_policy(self, db_session):
        policy = await save_policy(db_session, mode="blocklist", blocked=[], allowed=[])
        assert policy.blocked == frozenset() and policy.allowed == frozenset()
        assert json.loads((await db_session.get(SystemSetting, KEY_BLOCKED)).value) == []
        assert (await load_policy(db_session, use_cache=False)).blocked == frozenset()

    async def test_a_bad_mode_is_a_value_error_and_nothing_is_written(self, db_session):
        with pytest.raises(ValueError) as exc:
            await save_policy(db_session, mode="denylist", blocked=["exe"], allowed=["pdf"])
        assert "denylist" in str(exc.value)
        assert await db_session.get(SystemSetting, KEY_MODE) is None
        assert await db_session.get(SystemSetting, KEY_BLOCKED) is None

    async def test_the_mode_is_not_normalised_on_save(self, db_session):
        """The API layer normalises what it receives; the service refuses
        anything that is not exactly one of the two modes."""
        with pytest.raises(ValueError):
            await save_policy(db_session, mode="Allowlist", blocked=[], allowed=[])

    async def test_bad_entries_are_named_in_the_error_and_nothing_is_written(self, db_session):
        """The operator sees what was wrong rather than a silently shortened list."""
        with pytest.raises(ValueError) as exc:
            await save_policy(db_session, mode="blocklist", blocked=["exe", "tar.gz"], allowed=["pdf", "a b", ""])
        message = str(exc.value)
        assert "'tar.gz'" in message and "'a b'" in message and "''" in message
        assert "'exe'" not in message and "'pdf'" not in message
        assert await db_session.get(SystemSetting, KEY_BLOCKED) is None

    async def test_only_the_first_five_bad_entries_are_shown(self, db_session):
        bad = [f"bad.{i}" for i in range(7)]
        with pytest.raises(ValueError) as exc:
            await save_policy(db_session, mode="blocklist", blocked=bad, allowed=[])
        message = str(exc.value)
        assert all(f"'bad.{i}'" in message for i in range(5))
        assert "'bad.5'" not in message and "'bad.6'" not in message

    async def test_a_list_over_the_limit_is_refused(self, db_session):
        too_many = [f"e{i}" for i in range(MAX_LIST_ENTRIES + 1)]
        with pytest.raises(ValueError) as exc:
            await save_policy(db_session, mode="blocklist", blocked=too_many, allowed=[])
        assert str(MAX_LIST_ENTRIES) in str(exc.value)
        with pytest.raises(ValueError):
            await save_policy(db_session, mode="blocklist", blocked=[], allowed=too_many)
        assert await db_session.get(SystemSetting, KEY_MODE) is None

    async def test_the_limit_counts_after_deduplication(self, db_session):
        """600 spellings of ``exe`` are one entry."""
        exactly = [f"e{i}" for i in range(MAX_LIST_ENTRIES)]
        policy = await save_policy(db_session, mode="blocklist", blocked=exactly, allowed=["EXE", ".exe"] * 300)
        assert len(policy.blocked) == MAX_LIST_ENTRIES
        assert policy.allowed == frozenset({"exe"})


class TestResetPolicy:
    async def test_reset_restores_the_defaults_in_the_rows(self, db_session):
        await save_policy(db_session, mode="allowlist", blocked=["pdf"], allowed=["png"])
        assert (await load_policy(db_session, use_cache=False)) != DEFAULT_POLICY

        restored = await reset_policy(db_session)
        assert restored == DEFAULT_POLICY
        assert (await load_policy(db_session, use_cache=False)) == DEFAULT_POLICY

        assert (await db_session.get(SystemSetting, KEY_MODE)).value == "blocklist"
        assert json.loads((await db_session.get(SystemSetting, KEY_BLOCKED)).value) == sorted(DEFAULT_BLOCKED)
        assert json.loads((await db_session.get(SystemSetting, KEY_ALLOWED)).value) == sorted(DEFAULT_ALLOWED)

    async def test_reset_on_a_fresh_database_writes_the_rows(self, db_session):
        """ "Restore defaults" before any save is not an error and makes the
        defaults explicit in the table."""
        assert await reset_policy(db_session) == DEFAULT_POLICY
        assert await db_session.get(SystemSetting, KEY_MODE) is not None


class TestCache:
    async def test_a_cached_load_does_not_see_a_direct_row_change(self, db_session):
        """The cache exists so that five files in one message do not ask the
        database five times. This pins down what "cached" means."""
        first = await load_policy(db_session)
        assert first.mode == "blocklist"

        await _set_row(db_session, KEY_MODE, "allowlist")
        assert (await load_policy(db_session)).mode == "blocklist"
        assert (await load_policy(db_session)) is first

    async def test_invalidate_makes_the_next_load_read_the_database(self, db_session):
        await load_policy(db_session)
        await _set_row(db_session, KEY_MODE, "allowlist")

        invalidate_policy_cache()
        assert (await load_policy(db_session)).mode == "allowlist"

    async def test_use_cache_false_bypasses_and_refreshes_the_cache(self, db_session):
        await load_policy(db_session)
        await _set_row(db_session, KEY_MODE, "allowlist")

        assert (await load_policy(db_session, use_cache=False)).mode == "allowlist"
        # The uncached read replaced the cached value, not just bypassed it.
        assert (await load_policy(db_session)).mode == "allowlist"

    async def test_save_policy_invalidates_the_cache(self, db_session):
        """An administrator's save must be seen by the very next upload."""
        assert (await load_policy(db_session)).mode == "blocklist"
        saved = await save_policy(db_session, mode="allowlist", blocked=[], allowed=["pdf"])
        assert (await load_policy(db_session)) == saved

    async def test_the_cache_expires_after_the_ttl(self, db_session, monkeypatch):
        await load_policy(db_session)
        await _set_row(db_session, KEY_MODE, "allowlist")
        assert (await load_policy(db_session)).mode == "blocklist"

        monkeypatch.setattr(module, "CACHE_TTL_SECONDS", 0.0)
        assert (await load_policy(db_session)).mode == "allowlist"

    async def test_an_old_cache_entry_is_not_used(self, db_session):
        """Same thing from the other side: a timestamp older than the TTL."""
        policy = await load_policy(db_session)
        await _set_row(db_session, KEY_MODE, "allowlist")

        assert module._cache is not None and module._cache[1] is policy
        module._cache = (time.monotonic() - module.CACHE_TTL_SECONDS - 1.0, policy)
        assert (await load_policy(db_session)).mode == "allowlist"

    async def test_a_fresh_cache_entry_is_used(self, db_session):
        policy = await load_policy(db_session)
        await _set_row(db_session, KEY_MODE, "allowlist")

        module._cache = (time.monotonic() - module.CACHE_TTL_SECONDS / 2, policy)
        assert (await load_policy(db_session)) is policy

    async def test_reset_policy_invalidates_the_cache(self, db_session):
        await save_policy(db_session, mode="allowlist", blocked=[], allowed=["pdf"])
        assert (await load_policy(db_session)).mode == "allowlist"
        await reset_policy(db_session)
        assert (await load_policy(db_session)) == DEFAULT_POLICY


# --------------------------------------------------------------------------- #
# End to end
# --------------------------------------------------------------------------- #


class TestCheckUpload:
    async def test_an_unknown_binary_type_is_accepted_as_a_file(self, db_session):
        """The ``.psd`` case from the module docstring, end to end."""
        raw = b"8BPS\x00\x01" + bytes(range(256))
        assert await check_upload(db_session, filename="design.psd", raw=raw) == ("psd", "file")

    async def test_svg_bytes_behind_a_png_name_are_refused(self, db_session):
        with pytest.raises(UploadPolicyError) as exc:
            await check_upload(db_session, filename="logo.png", raw=SVG_BYTES)
        assert str(exc.value) == '"png" file rejected: its contents are HTML or SVG, not image.'

    async def test_a_blocked_name_is_refused_before_the_bytes_are_looked_at(self, db_session):
        with pytest.raises(UploadPolicyError) as exc:
            await check_upload(db_session, filename="setup.exe", raw=PNG_HEADER)
        assert '".exe"' in str(exc.value) and "not allowed on this platform" in str(exc.value)

    async def test_an_empty_upload_is_refused(self, db_session):
        with pytest.raises(UploadPolicyError) as exc:
            await check_upload(db_session, filename="a.pdf", raw=b"")
        assert str(exc.value) == "Empty file."

    async def test_the_saved_policy_is_honoured(self, db_session):
        raw = b"8BPS\x00\x01" + bytes(range(256))
        assert await check_upload(db_session, filename="design.psd", raw=raw) == ("psd", "file")

        await save_policy(db_session, mode="blocklist", blocked=sorted(DEFAULT_BLOCKED | {"psd"}), allowed=[])
        with pytest.raises(UploadPolicyError) as exc:
            await check_upload(db_session, filename="design.psd", raw=raw)
        assert str(exc.value) == 'File type ".psd" is not allowed on this platform.'

    async def test_the_saved_allowlist_is_honoured(self, db_session):
        await save_policy(db_session, mode="allowlist", blocked=["exe"], allowed=["pdf"])
        assert await check_upload(db_session, filename="a.pdf", raw=b"%PDF-1.4\n") == ("pdf", "document")
        with pytest.raises(UploadPolicyError) as exc:
            await check_upload(db_session, filename="a.png", raw=PNG_HEADER)
        assert "not on the list of allowed" in str(exc.value)

    async def test_an_unblocked_executable_name_is_still_stopped_by_its_bytes(self, db_session):
        """The two layers together: the operator unblocks ``.exe`` by name; a
        real PE file is still refused, a harmless file called ``.exe`` is not."""
        await save_policy(db_session, mode="blocklist", blocked=sorted(DEFAULT_BLOCKED - {"exe"}), allowed=[])
        with pytest.raises(UploadPolicyError) as exc:
            await check_upload(db_session, filename="tool.exe", raw=b"MZ\x90\x00" + b"\x00" * 60)
        assert "a Windows executable" in str(exc.value)
        assert await check_upload(db_session, filename="tool.exe", raw=b"not really an executable") == ("exe", "file")


class TestClassifyName:
    async def test_uses_the_defaults_when_nothing_is_saved(self, db_session):
        assert await classify_name(db_session, "design.psd") == ("psd", "file")
        with pytest.raises(UploadPolicyError):
            await classify_name(db_session, "setup.exe")

    async def test_uses_the_saved_policy(self, db_session):
        await save_policy(db_session, mode="allowlist", blocked=[], allowed=["pdf"])
        assert await classify_name(db_session, "a.pdf") == ("pdf", "document")
        with pytest.raises(UploadPolicyError) as exc:
            await classify_name(db_session, "design.psd")
        assert str(exc.value) == 'File type ".psd" is not on the list of allowed file types.'
        # An empty blocklist: what the defaults refused is now a name-only pass...
        await save_policy(db_session, mode="blocklist", blocked=[], allowed=[])
        assert await classify_name(db_session, "setup.exe") == ("exe", "file")

    async def test_sees_a_save_made_after_a_cached_load(self, db_session):
        assert await classify_name(db_session, "design.psd") == ("psd", "file")
        await save_policy(db_session, mode="blocklist", blocked=["psd"], allowed=[])
        with pytest.raises(UploadPolicyError):
            await classify_name(db_session, "design.psd")
