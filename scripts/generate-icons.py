"""Generate PWA icon set into frontend/public/icons/.

Usage: python scripts/generate-icons.py
"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent.parent / "frontend" / "public" / "icons"
OUT.mkdir(parents=True, exist_ok=True)

BG = (14, 165, 233)       # sky-500
FG = (255, 255, 255)
GLYPH_RATIO = 0.55        # within safe area
SAFE_RATIO = 0.8          # maskable safe area = central 80%


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for name in ("seguibl.ttf", "segoeuib.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def draw_icon(size: int, *, maskable: bool, transparent_corners: bool) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    if maskable:
        # full-bleed background — content centered in safe area
        d.rectangle([0, 0, size, size], fill=BG)
    elif transparent_corners:
        radius = int(size * 0.22)
        d.rounded_rectangle([0, 0, size, size], radius=radius, fill=BG)
    else:
        d.rectangle([0, 0, size, size], fill=BG)

    # Wallet-ish glyph: stylized "$"
    glyph_box = size * (SAFE_RATIO if maskable else 0.9)
    font = _font(int(glyph_box * GLYPH_RATIO * 1.1))
    text = "$"
    bbox = d.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    cx = (size - tw) / 2 - bbox[0]
    cy = (size - th) / 2 - bbox[1]
    d.text((cx, cy), text, font=font, fill=FG)
    return img


def main() -> None:
    targets = [
        ("icon-192.png", 192, False, True),
        ("icon-512.png", 512, False, True),
        ("icon-192-maskable.png", 192, True, False),
        ("icon-512-maskable.png", 512, True, False),
        ("apple-touch-icon.png", 180, False, False),  # iOS auto-masks; opaque square
    ]
    for name, size, maskable, transparent in targets:
        img = draw_icon(size, maskable=maskable, transparent_corners=transparent)
        path = OUT / name
        img.save(path, format="PNG", optimize=True)
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
