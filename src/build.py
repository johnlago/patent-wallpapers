"""Turn cached patent drawing sheets into e-ink sleep-screen wallpapers.

Usage:
    python src/build.py              # build everything in patents.toml
    python src/build.py US730918A    # build only the listed patents

Output (sizes come from [device] in patents.toml):
    output/light/*.bmp     black drawing on white   -> copy to SD card /.sleep/
    output/preview/*.png   PNG copies of the light set, for browsing
    output/contact-sheet.png
"""
from __future__ import annotations

import json
import re
import sys
import tomllib
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "cache"
OUT = ROOT / "output"

FONT_CANDIDATES = {
    "regular": ["fonts/regular.ttf", "~/Library/Fonts/Bookerly.ttf", "/System/Library/Fonts/Supplemental/Georgia.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf"],
    "italic": ["fonts/italic.ttf", "~/Library/Fonts/Bookerly Italic.ttf", "/System/Library/Fonts/Supplemental/Georgia Italic.ttf",
               "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Italic.ttf"],
}


def font(kind: str, size: int) -> ImageFont.FreeTypeFont:
    for p in FONT_CANDIDATES[kind]:
        path = Path(p).expanduser() if p[0] in "/~" else ROOT / p
        if path.exists():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default(size)


# ---------------------------------------------------------------- drawing prep

def ink_bbox(im: Image.Image, pad: int = 12) -> tuple[int, int, int, int]:
    """Bounding box of real ink, ignoring isolated scan specks."""
    f = 8
    small = im.resize((max(1, im.width // f), max(1, im.height // f)), Image.Resampling.BOX)
    mask = small.point(lambda v: 255 if v < 238 else 0)
    box = mask.getbbox()
    if not box:
        return (0, 0, im.width, im.height)
    l, t, r, b = (c * f for c in box)
    return (max(0, l - pad), max(0, t - pad), min(im.width, r + pad), min(im.height, b + pad))


def ink_bands(im: Image.Image) -> list[tuple[int, int]]:
    """Vertical runs of rows that contain ink, merging tiny gaps."""
    mask = im.point(lambda v: 255 if v < 128 else 0).resize((16, im.height), Image.Resampling.BOX)
    w = mask.width
    data = list(mask.getdata())
    rows = [max(data[y * w:(y + 1) * w]) > 0 for y in range(im.height)]
    bands, start, gap_ok = [], None, max(2, im.height // 250)
    last_ink = -10**9
    for y, ink in enumerate(rows):
        if ink:
            if start is None or y - last_ink > gap_ok:
                if start is not None:
                    bands.append((start, last_ink + 1))
                start = y
            last_ink = y
    if start is not None:
        bands.append((start, last_ink + 1))
    return bands


def strip_header(im: Image.Image) -> Image.Image:
    """Drop the printed 'U.S. Patent  <date>  Sheet N of M  <number>' line that
    sits alone at the top of modern drawing sheets. The caption already says it."""
    h = im.height
    bands = [b for b in ink_bands(im) if b[1] - b[0] > 0.004 * h]  # ignore specks
    if len(bands) < 2:
        return im
    (s0, e0), (s1, _) = bands[0], bands[1]
    if s0 < 0.25 * h and (e0 - s0) < 0.045 * im.width and (s1 - e0) > 0.01 * h:
        return im.crop((0, e0 + 1, im.width, h))
    return im


def prepare_drawing(src: Path, entry: dict, box_w: int, box_h: int) -> Image.Image:
    im = Image.open(src).convert("L")
    if entry.get("rotate"):
        im = im.rotate(entry["rotate"], expand=True, fillcolor=255)
    if crop := entry.get("crop"):
        l, t, r, b = crop
        im = im.crop((int(l * im.width), int(t * im.height), int(r * im.width), int(b * im.height)))

    # Flatten paper tone to pure white, stretch ink to full black.
    im = ImageOps.autocontrast(im, cutoff=(0.5, 0))
    paper = entry.get("paper", 185)  # lower = more aggressive background removal
    im = im.point(lambda v: 255 if v > paper else int(v * 255 / paper))
    # Median filter knocks out isolated scan specks while keeping real lines.
    if d := entry.get("despeckle", 3):
        im = im.filter(ImageFilter.MedianFilter(d))
    if entry.get("strip_header", True):
        im = strip_header(im)
    im = im.crop(ink_bbox(im))

    scale = min(box_w / im.width, box_h / im.height)
    # Thicken lines before downscaling so hairlines survive (~4-5x reduction typical).
    weight = entry.get("weight", 1)
    if weight and scale < 0.5:
        k = 3 if scale > 0.22 / weight else 5
        im = im.filter(ImageFilter.MinFilter(k))
    size = (max(1, round(im.width * scale)), max(1, round(im.height * scale)))
    return im.resize(size, Image.Resampling.LANCZOS)


def quantize(im: Image.Image, levels: int) -> Image.Image:
    """Snap to the panel's gray levels. Darken mid-tones first so thin
    anti-aliased lines land on a visible gray rather than white."""
    step = 255 / (levels - 1)
    lut = []
    for v in range(256):
        v2 = 255 * (v / 255) ** 1.7
        lut.append(int(round(round(v2 / step) * step)))
    return im.point(lut)


# ---------------------------------------------------------------- captions

def wrap(text: str, f: ImageFont.FreeTypeFont, width: int) -> list[str]:
    lines, cur = [], ""
    for word in text.split():
        trial = f"{cur} {word}".strip()
        if f.getlength(trial) <= width or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def pretty_number(number: str) -> str:
    digits = re.sub(r"\D", "", number)
    return f"{int(digits):,}"


def nice_title(t: str) -> str:
    t = t.strip().rstrip(".")
    return t[:1].upper() + t[1:]


def cap_height(f: ImageFont.FreeTypeFont) -> int:
    return -f.getbbox("H", anchor="ls")[1]


def caption_block(meta: dict, entry: dict, style: dict, width: int):
    """Return (height, draw_fn) for the caption so the drawing can be sized first.

    Lines are placed by baseline and cap height (not font size) so the visual
    gaps are what we ask for: rule -> header, header -> title, title -> inventor.
    The title sits optically centred between header and inventor; `title_nudge`
    shifts it down a touch to compensate for italic descenders below it.
    """
    year = (meta.get("publication_date") or "")[:4]
    header = f"U.S. PATENT  {pretty_number(meta['number'])}" + (f"  ·  {year}" if year else "")
    title = nice_title(entry.get("title") or meta["title"])
    inventor = entry.get("inventor") or ", ".join(meta.get("inventors", [])[:2])

    fh, ft, fi = font("regular", style["header_size"]), font("italic", style["title_size"]), font("regular", style["inventor_size"])
    title_lines = wrap(title, ft, width)
    lead = round(style["title_size"] * 1.22)
    ch, ct, ci = cap_height(fh), cap_height(ft), cap_height(fi)
    rule_gap, line_gap, nudge = style["rule_gap"], style["line_gap"], style.get("title_nudge", 0)

    # Baselines, relative to the rule at y=0.
    header_base = rule_gap + ch
    title_base0 = header_base + line_gap + ct + nudge
    title_last = title_base0 + lead * (len(title_lines) - 1)
    inventor_base = title_last + line_gap + ci - nudge if inventor else title_last
    descent = fi.getbbox("gjpy", anchor="ls")[3] if inventor else ft.getbbox("gjpy", anchor="ls")[3]
    height = inventor_base + descent

    def draw(d: ImageDraw.ImageDraw, x0: int, y0: int):
        cx = x0 + width // 2
        hw = style.get("rule_width", 36)
        d.line([(cx - hw, y0), (cx + hw, y0)], fill=0, width=1)
        d.text((cx, y0 + header_base), header, font=fh, fill=0, anchor="ms")
        for i, line in enumerate(title_lines):
            d.text((cx, y0 + title_base0 + i * lead), line, font=ft, fill=0, anchor="ms")
        if inventor:
            d.text((cx, y0 + inventor_base), inventor, font=fi, fill=0, anchor="ms")

    return height, draw


# ---------------------------------------------------------------- compose

def slug(meta: dict, entry: dict) -> str:
    words = re.sub(r"[^a-z0-9 ]", "", (entry.get("title") or meta["title"]).lower()).split()
    return f"{meta['number'].lower()}-" + "-".join(words[:5])


def build_one(entry: dict, device: dict, style: dict) -> tuple[str, Image.Image]:
    meta = json.loads((CACHE / entry["patent"] / "meta.json").read_text())
    W, H, m = device["width"], device["height"], style["margin"]
    cap_h, draw_caption = caption_block(meta, entry, style, W - 2 * m)

    box_w, box_h = W - 2 * m, H - 2 * m - cap_h - style["caption_gap"]
    drawing = prepare_drawing(CACHE / entry["patent"] / f"sheet-{entry.get('sheet', 0):02d}.png", entry, box_w, box_h)

    canvas = Image.new("L", (W, H), 255)
    # Center the drawing in its box; keep the caption pinned to the bottom.
    dx = m + (box_w - drawing.width) // 2
    dy = m + (box_h - drawing.height) // 2
    canvas.paste(drawing, (dx, dy))
    draw_caption(ImageDraw.Draw(canvas), m, H - m - cap_h)
    return slug(meta, entry), quantize(canvas, device["levels"])


def save_bmp(im: Image.Image, path: Path) -> None:
    # Mode "L" saves as an uncompressed 8-bit grayscale-palette BMP, which
    # CrossPoint's Bitmap loader accepts (it takes 1/2/4/8/24/32 bpp).
    # Pixels are already snapped to the panel's gray levels, so the device
    # shows exactly this image with no dithering of its own.
    im.save(path, format="BMP")


def contact_sheet(images: list[Image.Image], path: Path, cols: int = 5) -> None:
    w, h = images[0].size
    t = 0.4
    tw, th, g = int(w * t), int(h * t), 12
    rows = (len(images) + cols - 1) // cols
    sheet = Image.new("L", (cols * (tw + g) + g, rows * (th + g) + g), 200)
    for i, im in enumerate(images):
        x, y = g + (i % cols) * (tw + g), g + (i // cols) * (th + g)
        sheet.paste(im.resize((tw, th), Image.Resampling.LANCZOS), (x, y))
    sheet.save(path)


def main(argv: list[str]) -> None:
    cfg = tomllib.loads((ROOT / "patents.toml").read_text())
    device, style = cfg["device"], cfg["style"]
    entries = [e for e in cfg["wallpaper"] if not argv or e["patent"] in argv]
    for sub in ("light", "preview"):
        (OUT / sub).mkdir(parents=True, exist_ok=True)

    built = []
    for e in entries:
        if not (CACHE / e["patent"] / "meta.json").exists():
            print(f"{e['patent']}: not cached, run src/fetch.py first")
            continue
        name, im = build_one(e, device, style)
        save_bmp(im, OUT / "light" / f"{name}.bmp")
        im.save(OUT / "preview" / f"{name}.png", optimize=True)
        built.append(im)
        print(f"built {name}")
    if built and not argv:
        contact_sheet(built, OUT / "contact-sheet.png")
        print(f"{len(built)} wallpapers -> {OUT}")


if __name__ == "__main__":
    main(sys.argv[1:])
