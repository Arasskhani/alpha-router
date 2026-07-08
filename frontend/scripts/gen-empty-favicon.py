"""Generate transparent favicon.ico (16x16 PNG embedded in ICO container)."""
import struct
import zlib
from pathlib import Path


def _png_chunk(tag: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + tag
        + data
        + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    )


def _transparent_png(size: int) -> bytes:
    row = b"\x00" * (size * 4)
    raw = b"".join(b"\x00" + row for _ in range(size))
    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", zlib.compress(raw, 9))
        + _png_chunk(b"IEND", b"")
    )


def _write_ico(png_bytes: bytes, out_path: Path) -> None:
    header = struct.pack("<HHH", 0, 1, 1)
    entry = struct.pack("<BBBBHHII", 16, 16, 0, 0, 1, 32, len(png_bytes), 6 + 16)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(header + entry + png_bytes)


if __name__ == "__main__":
    png = _transparent_png(16)
    out = Path(__file__).resolve().parents[1] / "public" / "favicon.ico"
    _write_ico(png, out)
    print(f"wrote {out} ({out.stat().st_size} bytes)")
