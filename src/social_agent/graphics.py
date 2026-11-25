"""Make on-brand post images locally with Pillow, in the style of the brand's Canva designs.

Four layouts (see "layouts" in brand.json):
  cover     carousel cover: huge accent-color headline, page number, half-circle with an arrow
  list      numbered list: label tag, headline, 3-5 numbered rows, chevrons
  question  condensed uppercase headline with an underline
  card      email-style white card with headline, body and a notification pill

Colors, fonts, logo, handle and website come from brand.json. Fonts are bundled in assets/fonts
so images look the same on Streamlit Cloud. Put a transparent PNG logo at assets/logo.png to use
it instead of the drawn text logo.
"""
import json
import re
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
BRAND_PATH = ROOT / "brand.json"
EXPORT_DIR = ROOT / "data" / "exports"

SIZE = (1080, 1080)  # the brand's Canva designs are square
SIZES = {"instagram": SIZE, "facebook": SIZE, "linkedin": SIZE}
LAYOUTS = ["cover", "list", "question", "card"]
_OLD_STYLES = {"bold": "question", "light": "card", "accent": "cover"}  # earlier style names


def load_brand() -> dict:
    return json.loads(BRAND_PATH.read_text())


def _font(brand: dict, kind: str, size: int) -> ImageFont.FreeTypeFont:
    path = brand["fonts"].get(kind)
    try:
        return ImageFont.truetype(str(ROOT / path), size) if path else ImageFont.load_default(size)
    except OSError:
        return ImageFont.load_default(size)


def _wrap(d: ImageDraw.ImageDraw, text: str, font, max_w: int) -> list[str]:
    lines, line = [], ""
    for word in text.split():
        trial = f"{line} {word}".strip()
        if d.textlength(trial, font=font) <= max_w or not line:
            line = trial
        else:
            lines.append(line)
            line = word
    return lines + ([line] if line else [])


def _fit(d, brand, kind, text, max_w, max_h, start, minimum, spacing=1.05, max_lines=None):
    """Largest font size at which the wrapped text fits the box (and no word overflows)."""
    for size in range(start, minimum - 1, -2):
        font = _font(brand, kind, size)
        lines = _wrap(d, text, font, max_w)
        too_wide = any(d.textlength(line, font=font) > max_w for line in lines)
        if not too_wide and len(lines) * size * spacing <= max_h and (not max_lines or len(lines) <= max_lines):
            return font, lines, size
    font = _font(brand, kind, minimum)
    return font, _wrap(d, text, font, max_w), minimum


def _draw_lines(d, lines, font, size, x, y, fill, spacing=1.05, align="left", width=None):
    for line in lines:
        lx = x
        if align == "center":
            lx = x + (width - d.textlength(line, font=font)) / 2
        d.text((lx, y), line, font=font, fill=fill)
        y += int(size * spacing)
    return y


# ---------- brand pieces ----------

def _logo(img: Image.Image, brand: dict, cx: int | None, x: int, y: int, scale: float = 1.0) -> None:
    """Brand logo at (x, y), or centered on cx. Uses assets/logo.png when it exists."""
    d = ImageDraw.Draw(img)
    logo_file = ROOT / brand.get("logo_path", "") if brand.get("logo_path") else None
    if logo_file and logo_file.is_file():
        logo = Image.open(logo_file).convert("RGBA")
        logo.thumbnail((int(240 * scale), int(90 * scale)))
        lx = cx - logo.width // 2 if cx is not None else x
        img.paste(logo, (lx, y), logo)
        return
    c = brand["colors"]
    top, bottom = (brand.get("logo_text") or [brand["name"].upper(), ""])[:2]
    f = _font(brand, "heavy", int(30 * scale))
    tw = max(d.textlength(top, font=f), d.textlength(bottom, font=f))
    icon_w = int(44 * scale)
    total = icon_w + tw
    lx = int(cx - total / 2) if cx is not None else x
    # cursor-arrow icon with small sparks, like the brand mark
    s = scale
    ax, ay = lx + 6 * s, y + 18 * s
    d.polygon([(ax, ay), (ax + 30 * s, ay + 12 * s), (ax + 17 * s, ay + 17 * s), (ax + 25 * s, ay + 34 * s),
               (ax + 18 * s, ay + 37 * s), (ax + 10 * s, ay + 20 * s), (ax + 2 * s, ay + 30 * s)],
              fill=c["text_on_primary"])
    for dx, dy, ex, ey in [(-2, -6, -2, -14), (6, -6, 10, -13), (-8, 0, -15, -3)]:
        d.line([(ax + dx * s, ay + dy * s), (ax + ex * s, ay + ey * s)], fill=c["text_on_primary"], width=max(2, int(3 * s)))
    d.text((lx + icon_w, y), top, font=f, fill=c["text_on_primary"])
    d.text((lx + icon_w, y + int(30 * s)), bottom, font=f, fill=c["text_on_primary"])


def _footer(img: Image.Image, brand: dict) -> None:
    """Social icons + handle and website, bottom right (as on the brand's designs)."""
    d = ImageDraw.Draw(img)
    c = brand["colors"]
    w, h = img.size
    f = _font(brand, "medium", 30)
    small = _font(brand, "regular", 24)
    handle, site = brand.get("handle", ""), brand.get("website", "")
    right = w - 60
    hx = right - d.textlength(handle, font=f)
    y = h - 112
    d.text((hx, y), handle, font=f, fill=c["text_on_primary"])
    for i, letter in enumerate(["in", "ig", "f"]):  # three small round icons left of the handle
        r = 17
        cxp = hx - 26 - i * 42
        d.ellipse([cxp - r, y + 21 - r, cxp + r, y + 21 + r], fill=c["text_on_primary"])
        lf = _font(brand, "bold", 16)
        d.text((cxp - d.textlength(letter, font=lf) / 2, y + 11), letter, font=lf, fill=c["primary"])
    d.text((right - d.textlength(site, font=small), y + 44), site, font=small, fill=c["text_on_primary"])


# ---------- layouts ----------

def _cover(img, brand, headline, page, **_):
    d = ImageDraw.Draw(img)
    c = brand["colors"]
    w, h = img.size
    # gold half-circle on the right with a navy arrow
    r = w
    cx = w + r - int(w * 0.17)  # left edge of the circle at ~83% of the width
    d.ellipse([cx - r, h // 2 - r, cx + r, h // 2 + r], fill=c["accent"])
    ax, ay = w - 92, h // 2
    d.line([(ax - 18, ay - 34), (ax + 14, ay), (ax - 18, ay + 34)], fill=c["primary"], width=20, joint="curve")
    _logo(img, brand, None, 100, 100)
    pf = _font(brand, "bold", 30)
    d.text((w - 230, 100), page, font=pf, fill=c["text_on_primary"])
    font, lines, size = _fit(d, brand, "heavy", headline.upper(), int(w * 0.70), int(h * 0.56), 150, 60, 1.0)
    block_h = len(lines) * size
    _draw_lines(d, lines, font, size, 100, max(250, (h - block_h) // 2 + 30), c["accent"], 1.0)


def _list(img, brand, headline, label, items, **_):
    d = ImageDraw.Draw(img)
    c = brand["colors"]
    w, h = img.size
    pad = 82
    # chevrons, bottom right
    for off in (0, 150):
        d.line([(w - 380 + off, h + 20), (w - 130 + off, h - 230), (w + 120 + off, h + 20)],
               fill=c["accent"], width=48)
    _logo(img, brand, w // 2, 0, 52, 0.9)
    y = 190
    if label:
        lf = _font(brand, "bold", 34)
        tw = d.textlength(label.upper(), font=lf)
        d.rectangle([pad, y, pad + tw + 28, y + 52], fill=c["accent"])
        d.text((pad + 14, y + 4), label.upper(), font=lf, fill=c["primary"])
        y += 70
    font, lines, size = _fit(d, brand, "heavy", headline, w - 2 * pad, 250, 100, 52, 1.08, max_lines=2)
    y = _draw_lines(d, lines, font, size, pad, y, c["text_on_primary"], 1.08) + 26
    items = (items or [])[:5]
    if not items:
        return
    row_h = min(110, int((h - y - 40) / len(items)) - 16)
    tile_w = int(row_h * 1.25)
    box_right = int(w * 0.86)
    nf = _font(brand, "heavy", int(row_h * 0.62))
    for i, item in enumerate(items):
        top = y + i * (row_h + 16)
        d.rounded_rectangle([pad, top, box_right, top + row_h], radius=8, outline="#C9CED8", width=2,
                            fill=c["primary"])
        d.rounded_rectangle([pad, top, pad + tile_w, top + row_h], radius=8, fill=c["accent"])
        num = f"{i + 1:02d}"
        d.text((pad + (tile_w - d.textlength(num, font=nf)) / 2, top + row_h * 0.12), num, font=nf, fill=c["primary"])
        tf, tl, ts = _fit(d, brand, "medium", item, box_right - pad - tile_w - 44, row_h - 16, 42, 24, 1.15, 2)
        ty = top + (row_h - len(tl) * ts * 1.15) / 2
        _draw_lines(d, tl, tf, ts, pad + tile_w + 24, ty, c["text_on_primary"], 1.15)


def _question(img, brand, headline, **_):
    d = ImageDraw.Draw(img)
    c = brand["colors"]
    w, h = img.size
    pad = 70
    _logo(img, brand, w // 2, 0, 60, 1.0)
    font, lines, size = _fit(d, brand, "condensed", headline.upper(), w - 2 * pad, int(h * 0.58), 190, 80, 0.98)
    block_h = len(lines) * size * 0.98
    y = (h - block_h) / 2 + 40
    end = _draw_lines(d, lines, font, size, pad, y, c["text_on_primary"], 0.98, "center", w - 2 * pad)
    last_top = end - int(size * 0.98)
    bottom = d.textbbox((0, last_top), lines[-1], font=font)[3]  # real bottom of the last line's letters
    d.line([(w / 2 - 130, bottom + 28), (w / 2 + 130, bottom + 28)], fill=c["text_on_primary"], width=7)


def _card(img, brand, headline, subtext, label, **_):
    d = ImageDraw.Draw(img)
    c = brand["colors"]
    w, h = img.size
    _logo(img, brand, w // 2, 0, 46, 1.0)
    x0, y0, x1, y1 = 108, 185, w - 108, h - 165
    d.rounded_rectangle([x0, y0, x1, y1], radius=34, fill=c["card"])
    lf = _font(brand, "regular", 34)
    d.text((x0 + 70, y0 + 70), "To:", font=lf, fill=c["muted"])
    d.line([(x0 + 70, y0 + 135), (x1 - 70, y0 + 135)], fill="#C5CAD3", width=2)
    d.text((x0 + 70, y0 + 160), f"Subject: {label}" if label else "Subject:", font=lf, fill=c["muted"])
    d.line([(x0 + 70, y0 + 225), (x1 - 70, y0 + 225)], fill="#C5CAD3", width=2)
    inner = x1 - x0 - 140
    font, lines, size = _fit(d, brand, "bold", headline, inner, 200, 64, 36, 1.12, max_lines=3)
    y = _draw_lines(d, lines, font, size, x0 + 70, y0 + 265, c["text_on_card"], 1.12) + 14
    if subtext:
        bf, bl, bs = _fit(d, brand, "regular", subtext, inner, y1 - y - 210, 36, 24, 1.3)
        y = _draw_lines(d, bl, bf, bs, x0 + 70, y, c["text_on_card"], 1.3) + 26
    rf = _font(brand, "medium", 28)
    d.text((x0 + 70, y), "Read more >>>", font=rf, fill=c["link"])
    d.line([(x0 + 70, y + 36), (x0 + 70 + d.textlength("Read more >>>", font=rf), y + 36)], fill=c["link"], width=2)
    d.text((x0 + 70, y1 - 150), "Regards,", font=_font(brand, "regular", 32), fill=c["text_on_card"])
    d.text((x0 + 70, y1 - 105), brand["name"], font=_font(brand, "bold", 38), fill=c["text_on_card"])
    # notification pill, overlapping the card's top-right corner
    pf = _font(brand, "medium", 34)
    text = "New Email Received"
    pw = int(d.textlength(text, font=pf)) + 140
    px1, py0 = w - 40, y0 + 60
    d.rounded_rectangle([px1 - pw, py0, px1, py0 + 92], radius=46, fill=c["accent"])
    bx, by = px1 - pw + 58, py0 + 46
    d.pieslice([bx - 20, by - 24, bx + 20, by + 16], 180, 360, fill=c["text_on_primary"])
    d.rectangle([bx - 20, by - 4, bx + 20, by + 12], fill=c["text_on_primary"])
    d.ellipse([bx - 7, by + 12, bx + 7, by + 24], fill=c["text_on_primary"])
    d.ellipse([bx + 8, by - 30, bx + 22, by - 16], fill="#E53935")
    d.text((px1 - pw + 100, py0 + 20), text, font=pf, fill=c["text_on_primary"])
    _footer(img, brand)


_RENDER = {"cover": _cover, "list": _list, "question": _question, "card": _card}


def make_post_graphic(headline: str, subtext: str = "", platform: str = "instagram", style: str | None = None,
                      filename: str | None = None, layout: str | None = None, label: str = "",
                      items: list[str] | None = None, page: str = "01") -> Path:
    """Render a post image in one of the brand layouts and return its path (in data/exports/)."""
    brand = load_brand()
    layout = layout or _OLD_STYLES.get(style or "", None) or ("list" if items else "question")
    if layout not in _RENDER:
        raise ValueError(f"layout must be one of {LAYOUTS}")
    img = Image.new("RGB", SIZES.get(platform, SIZE), brand["colors"]["primary"])
    _RENDER[layout](img, brand, headline=headline, subtext=subtext, label=label, items=items, page=page)
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    if not filename:
        slug = re.sub(r"[^a-z0-9]+", "-", headline.lower()).strip("-")[:40]
        filename = f"{datetime.now():%Y%m%d-%H%M%S}-{layout}-{slug}.png"
    out = EXPORT_DIR / filename
    img.save(out)
    return out
