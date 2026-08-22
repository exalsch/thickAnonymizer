"""Generate packaging/icon.ico and packaging/splash.png.

Run once; the outputs are committed so a build machine does not need Pillow:
    python packaging/make_icon.py
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
ACCENT = (37, 99, 235, 255)
INK = (255, 255, 255, 255)
SPLASH_BG = (14, 17, 23, 255)
MUTED = (151, 161, 176, 255)
RULE = (44, 52, 64, 255)


def _font(size: int):
    for name in ("segoeuib.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _centered(draw, box, text, font, fill):
    left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    x = box[0] + (box[2] - box[0] - (right - left)) / 2 - left
    y = box[1] + (box[3] - box[1] - (bottom - top)) / 2 - top
    draw.text((x, y), text, font=font, fill=fill)


def make_icon() -> Path:
    size = 256
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((8, 8, size - 8, size - 8), radius=48, fill=ACCENT)
    _centered(draw, (8, 8, size - 8, size - 8), "TA", _font(120), INK)
    out = HERE / "icon.ico"
    image.save(out, sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)])
    return out


def make_splash() -> Path:
    width, height = 460, 280
    image = Image.new("RGBA", (width, height), SPLASH_BG)
    draw = ImageDraw.Draw(image)

    # Mark, top left, with the product name beside it.
    draw.rounded_rectangle((28, 40, 100, 112), radius=18, fill=ACCENT)
    _centered(draw, (28, 40, 100, 112), "TA", _font(38), INK)
    draw.text((118, 56), "thickAnonymizer", font=_font(24), fill=INK)
    draw.text((120, 90), "Starting up - the first launch takes a few seconds", font=_font(12), fill=MUTED)

    # A rule above the area the live status text is drawn into at run time.
    draw.line((28, 196, width - 28, 196), fill=RULE, width=1)

    out = HERE / "splash.png"
    image.convert("RGB").save(out)
    return out


if __name__ == "__main__":
    print(make_icon())
    print(make_splash())
