"""Extract Alpharouter mark from paper-background render → transparent PNG + SVG + favicons."""
from __future__ import annotations

import struct
import zlib
from pathlib import Path

import numpy as np
from PIL import Image

SRC = Path(
    r"C:\Users\M.Arasskhani\.cursor\projects\c-APPS-alpha-router\assets"
    r"\c__Users_M.Arasskhani_AppData_Roaming_Cursor_User_workspaceStorage_empty-window_images"
    r"_alpha-router-generated-image__7_-bb64c4d8-e61e-488b-89e6-7cfa421be85e.png"
)
PUBLIC = Path(__file__).resolve().parents[1] / "public"


def extract_mark(src: Path) -> Image.Image:
    im = Image.open(src).convert("RGBA")
    arr = np.asarray(im).copy()
    r, g, b, a = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2], arr[:, :, 3]
    # Paper background is light; keep darker ink + soft shadow fringe
    luminance = 0.2126 * r.astype(np.float32) + 0.7152 * g.astype(np.float32) + 0.0722 * b.astype(np.float32)
    # Soft alpha: darker → more opaque
    alpha = np.clip((215.0 - luminance) / 140.0, 0.0, 1.0)
    alpha = (alpha * 255.0).astype(np.uint8)
    # Kill near-paper noise
    alpha[luminance > 228] = 0
    arr[:, :, 3] = alpha

    ys, xs = np.where(alpha > 12)
    if len(xs) == 0:
        raise SystemExit("no logo pixels found")
    pad = 8
    left = max(0, int(xs.min()) - pad)
    right = min(arr.shape[1], int(xs.max()) + pad + 1)
    top = max(0, int(ys.min()) - pad)
    bottom = min(arr.shape[0], int(ys.max()) + pad + 1)
    cropped = Image.fromarray(arr, "RGBA").crop((left, top, right, bottom))

    # Normalize to square-ish canvas with padding for mark usage
    cw, ch = cropped.size
    side = max(cw, ch)
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.paste(cropped, ((side - cw) // 2, (side - ch) // 2), cropped)
    return canvas


def write_png(img: Image.Image, path: Path, size: int | None = None) -> None:
    out = img if size is None else img.resize((size, size), Image.Resampling.LANCZOS)
    path.parent.mkdir(parents=True, exist_ok=True)
    out.save(path, "PNG", optimize=True)
    print(f"wrote {path} {out.size}")


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
    print(f"wrote {path} ({path.stat().st_size} bytes)")


def write_svg_wrapper(png_name: str, path: Path, view: int = 512) -> None:
    # Keep .svg URL stable for existing references; embed PNG as data URI for crisp scaling.
    import base64

    png_path = PUBLIC / png_name
    b64 = base64.b64encode(png_path.read_bytes()).decode("ascii")
    svg = f"""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {view} {view}" width="{view}" height="{view}" role="img" aria-label="Alpharouter">
  <image width="{view}" height="{view}" href="data:image/png;base64,{b64}"/>
</svg>
"""
    path.write_text(svg, encoding="utf-8")
    print(f"wrote {path} ({path.stat().st_size} bytes)")


if __name__ == "__main__":
    mark = extract_mark(SRC)
    # Master PNG (high res)
    write_png(mark, PUBLIC / "alpha-router-mark.png", size=512)
    # Favicon sizes
    write_png(mark, PUBLIC / "favicon-32.png", size=32)
    write_ico(mark, PUBLIC / "favicon.ico", size=32)
    # SVG wrappers (stable paths used by app)
    write_svg_wrapper("alpha-router-mark.png", PUBLIC / "alpha-router-mark.svg", view=512)
    write_svg_wrapper("favicon-32.png", PUBLIC / "favicon.svg", view=32)
