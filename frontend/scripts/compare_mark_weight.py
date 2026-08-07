"""Compare mark stem weight vs Inter ExtraBold 'R' at wordmark size."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import numpy as np

PUBLIC = Path(r"C:\APPS\alpha-router\frontend\public")
OUT = Path(r"C:\APPS\alpha-router\frontend\public\_mark_weight_preview.png")

# Login-ish size ~ 48px cap height
cap = 48
mark = Image.open(PUBLIC / "alpha-router-mark.png").convert("RGBA")
# scale mark to cap height
mw, mh = mark.size
scale = cap / mh
mark_r = mark.resize((max(1, int(mw * scale)), cap), Image.Resampling.LANCZOS)

# Try common Windows Inter / Arial Black / Segoe
font = None
for path in [
    r"C:\Windows\Fonts\Inter-Bold.otf",
    r"C:\Windows\Fonts\Inter-SemiBold.otf",
    r"C:\Windows\Fonts\arialbd.ttf",
    r"C:\Windows\Fonts\segoeuib.ttf",
]:
    p = Path(path)
    if p.exists():
        try:
            font = ImageFont.truetype(str(p), cap)
            print("font", path)
            break
        except OSError:
            pass
if font is None:
    font = ImageFont.load_default()
    print("fallback default font")

canvas = Image.new("RGB", (420, 120), (241, 245, 249))
draw = ImageDraw.Draw(canvas)
# paste mark
canvas.paste(mark_r, (20, 30), mark_r)
# draw lpha Router
draw.text((20 + mark_r.width + 2, 30), "lpha Router", font=font, fill=(15, 23, 42))

# measure vertical stem width of mark at mid height
arr = np.asarray(mark_r)
a = arr[:, :, 3]
mid = a.shape[0] // 2
row = a[mid]
# find runs
on = row > 128
widths = []
i = 0
while i < len(on):
    if on[i]:
        j = i
        while j < len(on) and on[j]:
            j += 1
        widths.append(j - i)
        i = j
    else:
        i += 1
print("mark mid-row stroke widths (px):", widths)

# measure R stem from rendered text alone
text_img = Image.new("L", (200, 80), 0)
td = ImageDraw.Draw(text_img)
td.text((10, 10), "R", font=font, fill=255)
ta = np.asarray(text_img)
# find densest column band in left half (stem of R)
cols = (ta > 128).sum(axis=0)
# approximate stem: first solid vertical
for x in range(ta.shape[1]):
    if cols[x] > ta.shape[0] * 0.4:
        # measure width of this stem
        x2 = x
        while x2 < ta.shape[1] and cols[x2] > ta.shape[0] * 0.35:
            x2 += 1
        print("R approx stem width (px):", x2 - x)
        break

canvas.save(OUT)
print("wrote", OUT)
