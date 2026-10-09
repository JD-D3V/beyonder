"""Render the PWA icons from the Lucide book-open glyph used in components/icons.tsx.

    backend/.venv/bin/python frontend/scripts/gen-pwa-icons.py

Writes frontend/public/icons/{icon-192,icon-512,apple-touch-icon}.png.
Colours match the dark theme tokens in app/globals.css (--accent, --on-accent).
"""
import math
from pathlib import Path

from PIL import Image, ImageDraw

ACCENT = (88, 166, 255)  # --accent
INK = (13, 17, 23)  # --on-accent
SS = 4  # supersampling


def arc(cx, cy, a0, a1, r, n=16):
    return [
        (cx + r * math.cos(math.radians(a0 + (a1 - a0) * i / n)),
         cy + r * math.sin(math.radians(a0 + (a1 - a0) * i / n)))
        for i in range(n + 1)
    ]


# Same outline as the SVG path (24x24 viewBox, y down, stroke width 2).
OUTLINE = (
    [(3, 18)]
    + arc(3, 17, 90, 180, 1)  # to (2,17)
    + [(2, 4)]
    + arc(3, 4, 180, 270, 1)  # to (3,3)
    + [(8, 3)]
    + arc(8, 7, 270, 360, 4)  # to (12,7)
    + arc(16, 7, 180, 270, 4)  # to (16,3)
    + [(21, 3)]
    + arc(21, 4, 270, 360, 1)  # to (22,4)
    + [(22, 17)]
    + arc(21, 17, 0, 90, 1)  # to (21,18)
    + [(15, 18)]
    + arc(15, 21, 270, 180, 3)  # to (12,21)
    + arc(9, 21, 360, 270, 3)  # to (9,18)
    + [(3, 18)]
)
SPINE = [(12, 7), (12, 21)]


def render(size: int, glyph_frac: float, radius_frac: float) -> Image.Image:
    big = size * SS
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, big - 1, big - 1), radius=int(big * radius_frac), fill=ACCENT)
    scale = big * glyph_frac / 24
    off = (big - 24 * scale) / 2
    w = max(1, round(2 * scale))

    def line(pts):
        pts = [(off + x * scale, off + y * scale) for x, y in pts]
        d.line(pts, fill=INK, width=w, joint="curve")
        r = w / 2
        for x, y in (pts[0], pts[-1]):
            d.ellipse((x - r, y - r, x + r, y + r), fill=INK)

    line(OUTLINE)
    line(SPINE)
    return img.resize((size, size), Image.LANCZOS)


def main() -> None:
    out = Path(__file__).resolve().parent.parent / "public" / "icons"
    out.mkdir(parents=True, exist_ok=True)
    # Rounded "any" icons; the glyph sits well inside the maskable safe zone.
    render(192, 0.56, 0.2).save(out / "icon-192.png")
    render(512, 0.56, 0.2).save(out / "icon-512.png")
    # iOS applies its own mask, so it wants a full-bleed square.
    render(180, 0.56, 0.0).save(out / "apple-touch-icon.png")


if __name__ == "__main__":
    main()
