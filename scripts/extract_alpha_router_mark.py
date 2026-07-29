"""Extract clean wolf mark: drop paper/shadow fringe; keep solid black ink only."""
from __future__ import annotations

import argparse
import base64
import io
from collections import deque
from pathlib import Path

from PIL import Image

DEFAULT_SRC = Path(
    r"C:\Users\M.Arasskhani\.cursor\projects\c-APPS-Alpha Router\assets"
    r"\c__Users_M.Arasskhani_AppData_Roaming_Cursor_User_workspaceStorage"
    r"_empty-window_images_alpha-router-generated-image__44_-3a8f5ee8-0348-490e-9675-3e333f52e8b4.png"
)
PUBLIC = Path(r"C:\APPS\Alpha Router\frontend\public")

# Soft shadow / paper / mid-gray above this; solid ink is well below.
INK_MAX = 70


def extract(src: Path, out_png: Path, out_svg: Path) -> None:
    img = Image.open(src).convert("RGBA")
    w, h = img.size
    px = img.load()

    def lum(x: int, y: int) -> float:
        r, g, b, _a = px[x, y]
        return (r + g + b) / 3.0

    bg = [[False] * h for _ in range(w)]
    q: deque[tuple[int, int]] = deque()

    def try_seed(x: int, y: int) -> None:
        if not bg[x][y] and lum(x, y) > INK_MAX:
            bg[x][y] = True
            q.append((x, y))

    for x in range(w):
        try_seed(x, 0)
        try_seed(x, h - 1)
    for y in range(h):
        try_seed(0, y)
        try_seed(w - 1, y)

    while q:
        x, y = q.popleft()
        for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            if 0 <= nx < w and 0 <= ny < h and not bg[nx][ny] and lum(nx, ny) > INK_MAX:
                bg[nx][ny] = True
                q.append((nx, ny))

    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    opx = out.load()
    kept = 0
    for y in range(h):
        for x in range(w):
            if bg[x][y]:
                continue
            if lum(x, y) <= INK_MAX:
                opx[x, y] = (0, 0, 0, 255)
                kept += 1

    bbox = out.getbbox()
    if bbox:
        pad = 2
        out = out.crop(
            (
                max(0, bbox[0] - pad),
                max(0, bbox[1] - pad),
                min(w, bbox[2] + pad),
                min(h, bbox[3] + pad),
            )
        )

    out_png.parent.mkdir(parents=True, exist_ok=True)
    out.save(out_png, "PNG")

    cw, ch = out.size
    buf = io.BytesIO()
    out.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    out_svg.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {cw} {ch}" '
        f'width="{cw}" height="{ch}" role="img" aria-label="Alpha Router">\n'
        f'  <image width="{cw}" height="{ch}" href="data:image/png;base64,{b64}"/>\n'
        "</svg>\n",
        encoding="utf-8",
    )

    bg_frac = sum(1 for x in range(w) for y in range(h) if bg[x][y]) / (w * h)
    print(f"src={src.name}")
    print(f"png={out_png} size={out.size} ink={kept} bg_frac={bg_frac:.3f}")
    print(f"svg={out_svg}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--src", type=Path, default=DEFAULT_SRC)
    p.add_argument("--stem", default="alpha-router-mark", help="Output basename under frontend/public")
    args = p.parse_args()
    extract(args.src, PUBLIC / f"{args.stem}.png", PUBLIC / f"{args.stem}.svg")


if __name__ == "__main__":
    main()
