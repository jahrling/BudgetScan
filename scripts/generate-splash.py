"""Generate iOS launch images into frontend/public/splash/.

Usage: python scripts/generate-splash.py
"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent.parent / "frontend" / "public" / "splash"
OUT.mkdir(parents=True, exist_ok=True)

BG = (255, 255, 255)
ACCENT = (14, 165, 233)
FG = (255, 255, 255)


def _font(size: int):
    for name in ("seguibl.ttf", "segoeuib.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


# (filename, width, height, media-query for index.html)
TARGETS = [
    # iPhone 16/15/14 Pro (1179x2556 @3x)
    ("splash-1179x2556.png", 1179, 2556,
     "(device-width: 393px) and (device-height: 852px) and (-webkit-device-pixel-ratio: 3)"),
    # iPhone 14/13 Pro Max (1290x2796 @3x)
    ("splash-1290x2796.png", 1290, 2796,
     "(device-width: 430px) and (device-height: 932px) and (-webkit-device-pixel-ratio: 3)"),
    # iPhone 14/13/12 (1170x2532 @3x)
    ("splash-1170x2532.png", 1170, 2532,
     "(device-width: 390px) and (device-height: 844px) and (-webkit-device-pixel-ratio: 3)"),
    # iPhone SE 2/3 (750x1334 @2x)
    ("splash-750x1334.png", 750, 1334,
     "(device-width: 375px) and (device-height: 667px) and (-webkit-device-pixel-ratio: 2)"),
]


def draw_splash(w: int, h: int) -> Image.Image:
    img = Image.new("RGB", (w, h), BG)
    d = ImageDraw.Draw(img)
    disc = min(w, h) // 4
    cx, cy = w // 2, h // 2
    d.ellipse([cx - disc, cy - disc, cx + disc, cy + disc], fill=ACCENT)
    font = _font(int(disc * 1.1))
    text = "$"
    bbox = d.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    d.text((cx - tw / 2 - bbox[0], cy - th / 2 - bbox[1]), text, font=font, fill=FG)
    return img


def main() -> None:
    media_queries = []
    for name, w, h, mq in TARGETS:
        img = draw_splash(w, h)
        img.save(OUT / name, format="PNG", optimize=True)
        print(f"wrote {OUT / name}")
        media_queries.append((name, mq))

    print("\n<!-- iOS launch images — paste into index.html <head> -->")
    for name, mq in media_queries:
        print(
            f'<link rel="apple-touch-startup-image" '
            f'href="/splash/{name}" media="{mq}" />'
        )


if __name__ == "__main__":
    main()
