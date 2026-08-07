"""Thicken + solidify Alpha mark so stroke weight matches bold wordmark ink."""
from __future__ import annotations

import base64
import struct
import zlib
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

PUBLIC = Path(__file__).resolve().parents[1] / "public"
SRC_PNG = PUBLIC / "alpha-router-mark.png"


def png_chunk(tag: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)


def rgba_to_png_bytes(img: Image.Image) -> bytes:
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


def write_ico(img: Image.Image, path: Path, size: int = 32) -> None:
    sized = img.resize((size, size), Image.Resampling.LANCZOS)
    png = rgba_to_png_bytes(sized)
    header = struct.pack("<HHH", 0, 1, 1)
    entry = struct.pack("<BBBBHHII", size if size < 256 else 0, size if size < 256 else 0, 0, 0, 1, 32, len(png), 6 + 16)
    path.write_bytes(header + entry + png)
    print(f"wrote {path}")


def write_svg_wrapper(png_name: str, path: Path, view: int = 512) -> None:
    b64 = base64.b64encode((PUBLIC / png_name).read_bytes()).decode("ascii")
    path.write_text(
        f"""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {view} {view}" width="{view}" height="{view}" role="img" aria-label="Alpharouter">
  <image width="{view}" height="{view}" href="data:image/png;base64,{b64}"/>
</svg>
""",
        encoding="utf-8",
    )
    print(f"wrote {path}")


def thicken(im: Image.Image, dilate: int = 5) -> Image.Image:
    """Solid near-black ink + morphological thicken to match Inter ExtraBold stems."""
    arr = np.asarray(im.convert("RGBA")).astype(np.float32)
    r, g, b, a = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2], arr[:, :, 3]
    lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
    # Treat existing ink as coverage; crush gray fringe toward full ink
    coverage = np.clip(a / 255.0, 0.0, 1.0)
    # Prefer dark pixels; soft fringe from original alpha
    ink = coverage * np.clip((200.0 - lum) / 160.0 + 0.35, 0.0, 1.0)
    alpha_img = Image.fromarray((ink * 255.0).astype(np.uint8), mode="L")

    # Dilate to thicken strokes (MaxFilter uses odd kernel)
    k = dilate if dilate % 2 == 1 else dilate + 1
    thick = alpha_img
    for _ in range(2):
        thick = thick.filter(ImageFilter.MaxFilter(k))
    # Slight blur then re-threshold for smooth but solid edges
    soft = thick.filter(ImageFilter.GaussianBlur(radius=0.6))
    soft_arr = np.asarray(soft).astype(np.float32) / 255.0
    # Harder edge so it reads as bold type, not soft illustration
    solid = np.clip((soft_arr - 0.18) / 0.55, 0.0, 1.0)
    solid = np.power(solid, 0.85)

    out = np.zeros((im.height, im.width, 4), dtype=np.uint8)
    # Match login / topbar ink (#0f172a slate-900)
    out[:, :, 0] = 15
    out[:, :, 1] = 23
    out[:, :, 2] = 42
    out[:, :, 3] = (solid * 255.0).astype(np.uint8)
    return Image.fromarray(out, "RGBA")


def main() -> None:
    src = Image.open(SRC_PNG)
    print("src", src.size, src.mode)
    mark = thicken(src, dilate=5)
    mark.save(PUBLIC / "alpha-router-mark.png", "PNG", optimize=True)
    print("wrote alpha-router-mark.png")
    mark32 = mark.resize((32, 32), Image.Resampling.LANCZOS)
    mark32.save(PUBLIC / "favicon-32.png", "PNG", optimize=True)
    write_ico(mark, PUBLIC / "favicon.ico", size=32)
    write_svg_wrapper("alpha-router-mark.png", PUBLIC / "alpha-router-mark.svg", view=512)
    write_svg_wrapper("favicon-32.png", PUBLIC / "favicon.svg", view=32)


if __name__ == "__main__":
    main()
