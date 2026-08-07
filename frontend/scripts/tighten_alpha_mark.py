"""Tighten alpha-router-mark crop and regenerate favicons."""
from __future__ import annotations

import base64
import struct
import zlib
from pathlib import Path

import numpy as np
from PIL import Image

PUBLIC = Path(__file__).resolve().parents[1] / "public"


def png_chunk(tag: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)


def rgba_png(img: Image.Image) -> bytes:
    img = img.convert("RGBA")
    w, h = img.size
    raw = b"".join(b"\x00" + img.crop((0, y, w, y + 1)).tobytes() for y in range(h))
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + png_chunk(b"IHDR", ihdr)
        + png_chunk(b"IDAT", zlib.compress(raw, 9))
        + png_chunk(b"IEND", b"")
    )


def wrap_svg(png_name: str, out_name: str, view: int) -> None:
    b64 = base64.b64encode((PUBLIC / png_name).read_bytes()).decode("ascii")
    (PUBLIC / out_name).write_text(
        f"""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {view} {view}" width="{view}" height="{view}" role="img" aria-label="Alpharouter">
  <image width="{view}" height="{view}" href="data:image/png;base64,{b64}"/>
</svg>
""",
        encoding="utf-8",
    )


def main() -> None:
    im = Image.open(PUBLIC / "alpha-router-mark.png").convert("RGBA")
    a = np.asarray(im)
    ys, xs = np.where(a[:, :, 3] > 18)
    pad = 4
    left = max(0, int(xs.min()) - pad)
    right = min(a.shape[1], int(xs.max()) + pad + 1)
    top = max(0, int(ys.min()) - pad)
    bottom = min(a.shape[0], int(ys.max()) + pad + 1)
    cropped = Image.fromarray(a).crop((left, top, right, bottom))
    cw, ch = cropped.size
    side = max(cw, ch)
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.paste(cropped, ((side - cw) // 2, (side - ch) // 2), cropped)
    mark512 = canvas.resize((512, 512), Image.Resampling.LANCZOS)
    mark512.save(PUBLIC / "alpha-router-mark.png", "PNG", optimize=True)

    fav32 = mark512.resize((32, 32), Image.Resampling.LANCZOS)
    fav32.save(PUBLIC / "favicon-32.png", "PNG", optimize=True)
    png = rgba_png(fav32)
    header = struct.pack("<HHH", 0, 1, 1)
    entry = struct.pack("<BBBBHHII", 32, 32, 0, 0, 1, 32, len(png), 22)
    (PUBLIC / "favicon.ico").write_bytes(header + entry + png)

    wrap_svg("alpha-router-mark.png", "alpha-router-mark.svg", 512)
    wrap_svg("favicon-32.png", "favicon.svg", 32)

    ys2, xs2 = np.where(np.asarray(mark512)[:, :, 3] > 18)
    print(
        "content ratio",
        (xs2.max() - xs2.min()) / 512,
        (ys2.max() - ys2.min()) / 512,
    )


if __name__ == "__main__":
    main()
