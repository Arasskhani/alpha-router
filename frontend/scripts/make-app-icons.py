#!/usr/bin/env python3
"""Make the installed-app icons from the logo mark (needs Pillow).

    python3 scripts/make-app-icons.py      # from frontend/

Writes public/icons/: icon-192/512.png (mark at ~72 % of the width),
icon-maskable-192/512.png (full-bleed, mark inside the 80 % safe circle) and
apple-touch-icon.png (180 px; iOS paints transparency black, so the
background is opaque). All on white, the mark black. Run it again when the
mark changes and commit the results.
"""

from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent.parent
MARK = HERE / "public" / "alpha-router-mark.png"
OUT = HERE / "public" / "icons"

# (file, size, share of the width the mark's longer side takes)
ICONS = [
    ("icon-192.png", 192, 0.72),
    ("icon-512.png", 512, 0.72),
    ("icon-maskable-192.png", 192, 0.56),
    ("icon-maskable-512.png", 512, 0.56),
    ("apple-touch-icon.png", 180, 0.70),
]


def make(size: int, share: float, mark: Image.Image) -> Image.Image:
    side = round(size * share)
    scale = side / max(mark.size)
    art = mark.resize((round(mark.width * scale), round(mark.height * scale)), Image.LANCZOS)
    icon = Image.new("RGBA", (size, size), (255, 255, 255, 255))
    icon.alpha_composite(art, ((size - art.width) // 2, (size - art.height) // 2))
    return icon.convert("RGB")


def main() -> None:
    mark = Image.open(MARK).convert("RGBA")
    mark = mark.crop(mark.getchannel("A").getbbox())
    OUT.mkdir(parents=True, exist_ok=True)
    for name, size, share in ICONS:
        make(size, share, mark).save(OUT / name, optimize=True)
        print(f"wrote {OUT / name}")


if __name__ == "__main__":
    main()
