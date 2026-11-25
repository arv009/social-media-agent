"""Make simple on-brand post images locally with Pillow (no Canva account needed).

Colors, fonts and logo come from brand.json in the project folder. The image can be
used as-is, or uploaded to Canva by the Canva connector for polishing.
"""
import json
import re
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
BRAND_PATH = ROOT / "brand.json"
EXPORT_DIR = ROOT / "data" / "exports"

SIZES = {  # good default sizes per platform (width, height)
    "instagram": (1080, 1350),   # 4:5 portrait fills the feed best
    "facebook": (1080, 1080),
    "linkedin": (1080, 1080),
}
STYLES = ["bold", "light", "accent"]


def load_brand() -> dict:
    return json.loads(BRAND_PATH.read_text())


def _font(path: str | None, size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(path, size) if path else ImageFont.load_default(size)
    except OSError:
        return ImageFont.load_default(size)


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> list[str]:
    lines, line = [], ""
    for word in text.split():
        trial = f"{line} {word}".strip()
        if draw.textlength(trial, font=font) <= max_width or not line:
            line = trial
        else:
            lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


def _fit(draw, text, font_path, max_width, max_height, start, minimum, spacing=1.15):
    """Largest font size where the wrapped text fits the box."""
    size = start
    while size > minimum:
        font = _font(font_path, size)
        lines = _wrap(draw, text, font, max_width)
        if len(lines) * size * spacing <= max_height:
            return font, lines, size
        size -= 4
    font = _font(font_path, minimum)
    return font, _wrap(draw, text, font, max_width), minimum


def make_post_graphic(headline: str, subtext: str = "", platform: str = "instagram",
                      style: str = "bold", filename: str | None = None) -> Path:
    """Render a post image and return its path (in data/exports/)."""
    brand = load_brand()
    c, f = brand["colors"], brand["fonts"]
    w, h = SIZES.get(platform, (1080, 1080))
    style = style if style in STYLES else "bold"
    bg = {"bold": c["primary"], "light": c["background"], "accent": c["accent"]}[style]
    fg = c["text_on_primary"] if style == "bold" else c["text_on_background"]
    img = Image.new("RGB", (w, h), bg)
    d = ImageDraw.Draw(img)
    pad = int(w * 0.09)

    # decoration: accent bar (bold/light) or primary bar (accent style)
    bar_color = c["primary"] if style == "accent" else c["accent"]
    d.rectangle([pad, pad, pad + int(w * 0.14), pad + 14], fill=bar_color)

    # logo top-right
    if brand.get("logo_path") and (ROOT / brand["logo_path"]).exists():
        logo = Image.open(ROOT / brand["logo_path"]).convert("RGBA")
        logo.thumbnail((int(w * 0.18), int(w * 0.18)))
        img.paste(logo, (w - pad - logo.width, pad - 10), logo)

    # headline
    top = pad + 70
    box_w = w - 2 * pad
    font, lines, size = _fit(d, headline, f.get("headline"), box_w, int(h * 0.48), start=120, minimum=48)
    y = top
    for line in lines:
        d.text((pad, y), line, font=font, fill=fg)
        y += int(size * 1.15)

    # subtext
    if subtext:
        y += int(size * 0.5)
        sub_font, sub_lines, sub_size = _fit(d, subtext, f.get("body"), box_w, h - y - pad - 110,
                                             start=52, minimum=28, spacing=1.35)
        for line in sub_lines:
            d.text((pad, y), line, font=sub_font, fill=fg)
            y += int(sub_size * 1.35)

    # footer: brand name + handle
    foot = _font(f.get("headline"), 34)
    d.line([pad, h - pad - 60, w - pad, h - pad - 60], fill=fg, width=2)
    d.text((pad, h - pad - 40), brand.get("name", ""), font=foot, fill=fg)
    handle = brand.get("handle", "")
    d.text((w - pad - d.textlength(handle, font=foot), h - pad - 40), handle, font=foot, fill=fg)

    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    if not filename:
        slug = re.sub(r"[^a-z0-9]+", "-", headline.lower()).strip("-")[:40]
        filename = f"{datetime.now():%Y%m%d-%H%M%S}-{platform}-{slug}.png"
    out = EXPORT_DIR / filename
    img.save(out)
    return out
