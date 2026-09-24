#!/usr/bin/env python3
"""Make the installed-app icons from the logo mark (needs Pillow).

    python3 scripts/make-app-icons.py      # from frontend/

Writes public/icons/: icon-192/512.png (mark at ~72 % of the width),
icon-maskable-192/512.png (full-bleed, mark inside the 80 % safe circle) and
apple-touch-icon.png (180 px; iOS paints transparency black, so the
background is opaque). All on white, the mark black.

Also writes the browser extension's icons to extension/public/icons/
(icon-16/32/48/128.png): the mark on a white rounded square, so it stays
visible on a dark toolbar. Run it again when the mark changes and commit the
results.
"""

from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent.parent
MARK = HERE / "public" / "alpha-router-mark.png"
OUT = HERE / "public" / "icons"
EXTENSION_OUT = HERE / "extension" / "public" / "icons"

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


# (file, size, share of the width the mark takes) for the extension's toolbar,
# menu and management-page icons.
EXTENSION_ICONS = [
    ("icon-16.png", 16, 0.78),
    ("icon-32.png", 32, 0.72),
    ("icon-48.png", 48, 0.70),
    ("icon-128.png", 128, 0.66),
]


def make_extension(size: int, share: float, mark: Image.Image) -> Image.Image:
    # Drawn at four times the size and scaled down, for smooth corners.
    big = size * 4
    icon = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    ImageDraw.Draw(icon).rounded_rectangle((0, 0, big - 1, big - 1), radius=round(big * 0.22), fill=(255, 255, 255, 255))
    side = round(big * share)
    scale = side / max(mark.size)
    art = mark.resize((round(mark.width * scale), round(mark.height * scale)), Image.LANCZOS)
    icon.alpha_composite(art, ((big - art.width) // 2, (big - art.height) // 2))
    return icon.resize((size, size), Image.LANCZOS)


def main() -> None:
    mark = Image.open(MARK).convert("RGBA")
    mark = mark.crop(mark.getchannel("A").getbbox())
    OUT.mkdir(parents=True, exist_ok=True)
    for name, size, share in ICONS:
        make(size, share, mark).save(OUT / name, optimize=True)
        print(f"wrote {OUT / name}")
    EXTENSION_OUT.mkdir(parents=True, exist_ok=True)
    for name, size, share in EXTENSION_ICONS:
        make_extension(size, share, mark).save(EXTENSION_OUT / name, optimize=True)
        print(f"wrote {EXTENSION_OUT / name}")


if __name__ == "__main__":
    main()
