"""Turn cached patent drawing sheets into e-ink sleep-screen wallpapers.

Usage:
    python src/build.py              # build everything in patents.toml
    python src/build.py US730918A    # build only the listed patents

Output (sizes come from [device] in patents.toml):
    output/2bpp/*.bmp      true 2-bit, exact screen size: shown pixel-for-pixel -> SD card /.sleep/
    output/gray-2000/*.png full-grayscale reference copies, same layout scaled to 2000 px tall
    output/preview/*.png   PNG copies of the 2bpp set, for browsing
    output/contact-sheet.png
"""
from __future__ import annotations

import json
import struct
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

def ink_clusters(im: Image.Image, f: int = 8, link: int = 6) -> list[dict]:
    """Group ink into clusters: marks within ~2*link*f source px of each other
    join the same cluster. Returns [{mass, box}] with boxes in source pixels."""
    small = im.resize((max(1, im.width // f), max(1, im.height // f)), Image.Resampling.BOX)
    mask = small.point(lambda v: 255 if v < 238 else 0)
    linked = mask.filter(ImageFilter.MaxFilter(2 * link + 1))
    w, h = mask.size
    mp, lp = mask.load(), linked.load()
    seen = bytearray(w * h)
    clusters = []
    for y0 in range(h):
        for x0 in range(w):
            if not lp[x0, y0] or seen[y0 * w + x0]:
                continue
            stack, mass, box = [(x0, y0)], 0, [w, h, 0, 0]
            seen[y0 * w + x0] = 1
            while stack:
                x, y = stack.pop()
                if mp[x, y]:
                    mass += 1
                    box = [min(box[0], x), min(box[1], y), max(box[2], x + 1), max(box[3], y + 1)]
                for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                    if 0 <= nx < w and 0 <= ny < h and lp[nx, ny] and not seen[ny * w + nx]:
                        seen[ny * w + nx] = 1
                        stack.append((nx, ny))
            if mass:
                clusters.append({"mass": mass, "box": tuple(c * f for c in box)})
    return clusters


def ink_bbox(im: Image.Image, pad: int = 12, min_share: float = 0.003) -> tuple[int, int, int, int]:
    """Bounding box of the real drawing. Isolated scan specks and smudges (tiny,
    far-away clusters) are ignored, so the drawing is re-centred on its actual
    content instead of on stray marks near the sheet edge."""
    clusters = ink_clusters(im)
    if not clusters:
        return (0, 0, im.width, im.height)
    total = sum(c["mass"] for c in clusters)
    keep = [c["box"] for c in clusters if c["mass"] >= min_share * total] or [c["box"] for c in clusters]
    l, t = min(b[0] for b in keep), min(b[1] for b in keep)
    r, b_ = max(b[2] for b in keep), max(b[3] for b in keep)
    return (max(0, l - pad), max(0, t - pad), min(im.width, r + pad), min(im.height, b_ + pad))


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
    return fit_drawing(clean_drawing(src, entry), entry, box_w, box_h)


def clean_drawing(src: Path, entry: dict) -> Image.Image:
    """Full-resolution drawing: rotated, cropped, paper flattened, trimmed to ink."""
    im = Image.open(src).convert("L")
    if entry.get("rotate"):
        im = im.rotate(entry["rotate"], expand=True, fillcolor=255)
    if crop := entry.get("crop"):
        l, t, r, b = crop
        im = im.crop((int(l * im.width), int(t * im.height), int(r * im.width), int(b * im.height)))
    for l, t, r, b in entry.get("erase", []):  # white out stray bits the crop can't avoid
        im.paste(255, (int(l * im.width), int(t * im.height), int(r * im.width), int(b * im.height)))

    # Flatten paper tone to pure white, stretch ink to full black.
    im = ImageOps.autocontrast(im, cutoff=(0.5, 0))
    paper = entry.get("paper", 185)  # lower = more aggressive background removal
    im = im.point(lambda v: 255 if v > paper else int(v * 255 / paper))
    # Median filter knocks out isolated scan specks while keeping real lines.
    if d := entry.get("despeckle", 3):
        im = im.filter(ImageFilter.MedianFilter(d))
    if entry.get("strip_header", True):
        im = strip_header(im)
    return im.crop(ink_bbox(im))


def fit_drawing(im: Image.Image, entry: dict, box_w: int, box_h: int) -> Image.Image:
    """Scale a cleaned drawing to fit the box, thickening hairlines first."""
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

# Title setting follows ordinary display-typesetting practice:
#   1. A title that only just overflows is set on one line, slightly smaller,
#      rather than broken (shrinking is cheap, a break is not).
#   2. Break by sense: never leave a short function word ("for", "of", "the")
#      hanging at the end of a line; prefer breaking *before* a preposition or
#      conjunction, so each line is a phrase.
#   3. No single-word line if a better option exists.
#   4. Among sensible breaks, keep the two lines reasonably balanced, with the
#      bottom line a little longer when it's close.
# Each candidate (size, lines) gets a cost; the cheapest wins.

ARTICLES = {"a", "an", "the"}
CONNECTIVES = {  # prepositions + conjunctions: natural phrase starts
    "of", "for", "to", "by", "in", "on", "at", "from", "with", "and", "or", "but",
    "nor", "as", "into", "onto", "upon", "via", "per", "than",
}
WEAK_WORDS = ARTICLES | CONNECTIVES
SHRINK_COST = 0.04       # per px below the normal title size
BREAK_COST = 0.30        # any break at all (vs one line)
WEAK_END_COST = 1.0      # line 1 ends on a weak word ("Device for /")
SINGLE_WORD_COST = 0.5   # a line holding just one word
SENSE_BREAK_BONUS = 0.25  # line 2 starts with a preposition/conjunction ("/ for kicking ...")
ARTICLE_START_COST = 0.1  # line 2 starts with "a"/"the": splits a phrase from its noun
IDEAL_RATIO = 0.85       # ideal line-1 width as a fraction of line 2


def break_cost(l1: str, l2: str, f: ImageFont.FreeTypeFont) -> float:
    q = f.getlength(l1) / f.getlength(l2)
    cost = (q - IDEAL_RATIO) ** 2
    if l1.split()[-1].lower() in WEAK_WORDS:
        cost += WEAK_END_COST
    if " " not in l1 or " " not in l2:
        cost += SINGLE_WORD_COST
    if l2.split()[0].lower() in CONNECTIVES:
        cost -= SENSE_BREAK_BONUS
    elif l2.split()[0].lower() in ARTICLES:
        cost += ARTICLE_START_COST
    return cost


def set_title(title: str, max_size: int, min_size: int, width: int, max_lines: int = 2) -> tuple[int, list[str]]:
    """Choose the title's size and line breaks (one or two lines). If no size
    fits two lines and `max_lines` > 2, take the largest size whose balanced
    wrap fits in `max_lines` (narrow caption columns)."""
    words = title.split()
    best = None
    for size in range(max_size, min_size - 1, -1):
        f = font("italic", size)
        shrink = SHRINK_COST * (max_size - size)
        options = []
        if f.getlength(title) <= width:
            options.append((shrink, [title]))
        for k in range(1, len(words)):
            l1, l2 = " ".join(words[:k]), " ".join(words[k:])
            if max(f.getlength(l1), f.getlength(l2)) <= width:
                options.append((shrink + BREAK_COST + break_cost(l1, l2, f), [l1, l2]))
        for cost, lines in options:
            if best is None or cost < best[0]:
                best = (cost, size, lines)
    if best:
        return best[1], best[2]
    for size in range(max_size, min_size - 1, -1):
        lines = wrap(title, font("italic", size), width)
        if len(lines) <= max_lines and max(font("italic", size).getlength(l) for l in lines) <= width:
            return size, lines
    return min_size, wrap(title, font("italic", min_size), width)  # last resort: 3+ lines


def wrap(text: str, f: ImageFont.FreeTypeFont, width: int) -> list[str]:
    """Balanced wrap: use as few lines as greedy wrapping would, but choose the
    breaks that minimise the summed squared slack of every line (last included),
    so lines come out evenly long with no orphan words or stubby first lines."""
    words = text.split()
    n, cur = 1, ""
    for w in words:  # greedy pass just to count lines
        trial = f"{cur} {w}".strip()
        if f.getlength(trial) > width and cur:
            n, cur = n + 1, w
        else:
            cur = trial
    if n == 1:
        return [text]

    from functools import lru_cache

    @lru_cache(None)
    def best(i: int, k: int) -> tuple[float, tuple[str, ...]]:
        # lay out words[i:] in exactly k lines -> (cost, lines)
        if k == 1:
            line = " ".join(words[i:])
            lw = f.getlength(line)
            return ((width - lw) ** 2 if lw <= width else float("inf")), (line,)
        result = (float("inf"), ())
        for j in range(i + 1, len(words) - k + 2):
            line = " ".join(words[i:j])
            lw = f.getlength(line)
            if lw > width:
                break
            rest_cost, rest = best(j, k - 1)
            cand = ((width - lw) ** 2 + rest_cost, (line,) + rest)
            if cand[0] < result[0]:
                result = cand
        return result

    return list(best(0, n)[1])


def tidy_name(name: str) -> str:
    """Consistent punctuation for inventor names: a period after every single-
    letter initial ("Samuel S Applegate" -> "Samuel S. Applegate") and after
    Jr/Sr ("Andrew Jackson Jr" -> "Andrew Jackson Jr.")."""
    name = re.sub(r"\b([A-Z])\b(?!\.)", r"\1.", name)
    return re.sub(r"\b(Jr|Sr)\b(?!\.)", r"\1.", name)


def pretty_number(number: str) -> str:
    digits = re.sub(r"\D", "", re.sub(r"[A-Z]\d?$", "", number.upper()[2:]))
    return f"{int(digits):,}"


def nice_title(t: str) -> str:
    t = t.strip().rstrip(".")
    return t[:1].upper() + t[1:]


def cap_height(f: ImageFont.FreeTypeFont) -> int:
    return -f.getbbox("H", anchor="ls")[1]


def caption_text(meta: dict, entry: dict, style: dict) -> tuple[str, str, str, str, str]:
    """(header, number, year, title, inventor) strings for a caption."""
    year = str(entry.get("year") or (meta.get("publication_date") or "")[:4])
    number = f"U.S. PATENT NO. {pretty_number(meta['number'])}"
    header = number + (f"  ·  {year}" if year else "")
    title = nice_title(entry.get("title") or meta["title"])
    inventor = entry.get("inventor") or ", ".join(
        tidy_name(n) for n in meta.get("inventors", [])[:style.get("max_inventors", 2)])
    return header, number, year, title, inventor


def caption_block(meta: dict, entry: dict, style: dict, width: int):
    """Return (height, draw_fn) for the caption so the drawing can be sized first.

    Lines are placed by baseline and cap height (not font size) so the visual
    gaps are what we ask for: rule -> header, header -> title, title -> inventor.
    The title sits optically centred between header and inventor; `title_nudge`
    moves it (negative = up) without moving the header or inventor lines.

    Optional style keys (for small layouts): `show_header` / `show_inventor`
    (default true) drop those lines, `show_rule` (default true) drops the divider,
    and `max_inventors` (default 2) limits names. A header or inventor line too
    wide for `width` wraps instead of overflowing; `header_wrap = false` keeps
    the header on one line (the caller must make `width` wide enough).
    """
    show_header, show_inventor = style.get("show_header", True), style.get("show_inventor", True)
    show_rule = show_header and style.get("show_rule", True)
    header, number, year, title, inventor = caption_text(meta, entry, style)
    if not show_inventor:
        inventor = ""

    fh, fi = font("regular", style["header_size"]), font("regular", style["inventor_size"])
    header_lines = [header] if show_header else []
    if header_lines and style.get("header_wrap", True) and fh.getlength(header) > width:
        header_lines = [number] + ([year] if year else [])
    inventor_lines = wrap(inventor, fi, width) if inventor else []
    # Title: one line if it fits, else the best two-line split. If even that
    # overflows, step the size down until it fits (never more than two lines).
    size, title_lines = set_title(title, style["title_size"], style.get("title_min_size", 16), width,
                                  style.get("max_title_lines", 2))
    ft = font("italic", size)
    lead = round(size * 1.22)
    header_lead, inventor_lead = round(style["header_size"] * 1.3), round(style["inventor_size"] * 1.3)
    ch, ct, ci = cap_height(fh), cap_height(ft), cap_height(fi)
    rule_gap = style["rule_gap"] if show_rule else 0
    line_gap, nudge = style["line_gap"], style.get("title_nudge", 0)
    # header_nudge < 0 lifts the header (and the rule above it) away from the
    # title; the caption grows by that much and the drawing box shrinks to match.
    header_nudge = style.get("header_nudge", 0)

    # Baselines, relative to the rule at y=0 (or the caption top, with no header).
    if header_lines:
        header_base = rule_gap + ch
        header_last = header_base + header_lead * (len(header_lines) - 1)
        title_base0 = header_last + line_gap + ct + nudge - header_nudge
    else:
        title_base0 = ct
    title_last = title_base0 + lead * (len(title_lines) - 1)
    inventor_base = title_last + line_gap + ci - nudge if inventor_lines else title_last
    inventor_last = inventor_base + inventor_lead * max(0, len(inventor_lines) - 1)
    descent = fi.getbbox("gjpy", anchor="ls")[3] if inventor_lines else ft.getbbox("gjpy", anchor="ls")[3]
    height = inventor_last + descent

    def draw(d: ImageDraw.ImageDraw, x0: int, y0: int):
        cx = x0 + width // 2
        if show_rule:
            hw = style.get("rule_width", 36)
            d.line([(cx - hw, y0), (cx + hw, y0)], fill=0, width=style.get("rule_thickness", 1))
        if header_lines:
            for i, line in enumerate(header_lines):
                d.text((cx, y0 + header_base + i * header_lead), line, font=fh, fill=0, anchor="ms")
        for i, line in enumerate(title_lines):
            d.text((cx, y0 + title_base0 + i * lead), line, font=ft, fill=0, anchor="ms")
        for i, line in enumerate(inventor_lines):
            d.text((cx, y0 + inventor_base + i * inventor_lead), line, font=fi, fill=0, anchor="ms")

    return height, draw


# ---------------------------------------------------------------- compose

def slug(meta: dict, entry: dict) -> str:
    words = re.sub(r"[^a-z0-9 ]", "", (entry.get("title") or meta["title"]).lower()).split()
    return f"{meta['number'].lower()}-" + "-".join(words[:5])


def build_one(entry: dict, device: dict, style: dict, height: int | None = None) -> tuple[str, Image.Image]:
    """Compose one wallpaper. With `height`, the whole layout (margins, type,
    spacing) is scaled up proportionally to that canvas height."""
    meta = json.loads((CACHE / entry["patent"] / "meta.json").read_text())
    k = (height / device["height"]) if height else 1.0
    style = {key: (round(v * k) if isinstance(v, (int, float)) else v) for key, v in style.items()}
    style["rule_thickness"] = max(1, round(k))
    W, H, m = round(device["width"] * k), round(device["height"] * k), style["margin"]
    cap_h, draw_caption = caption_block(meta, entry, style, W - 2 * m)

    box_w, box_h = W - 2 * m, H - 2 * m - cap_h - style["caption_gap"]
    drawing = prepare_drawing(CACHE / entry["patent"] / f"sheet-{entry.get('sheet', 0):02d}.png", entry, box_w, box_h)

    canvas = Image.new("L", (W, H), 255)
    # Center the drawing in its box; keep the caption pinned to the bottom.
    dx = m + (box_w - drawing.width) // 2
    dy = m + (box_h - drawing.height) // 2
    canvas.paste(drawing, (dx, dy))
    draw_caption(ImageDraw.Draw(canvas), m, H - m - cap_h)
    return slug(meta, entry), canvas


def save_bmp_2bpp(im: Image.Image, path: Path) -> None:
    """Write a true 2-bit BMP with a 4-entry palette (black, dark, light, white).

    CrossPoint draws a sleep image as-is only when it is exactly screen-sized
    and <= 2 bpp. Anything else (including 8-bit BMPs whose pixels already sit
    on the 4 levels) goes through its converter, which Atkinson-dithers with
    X4-tuned thresholds (<45 black, <70 dark, <140 light, else white) and turns
    our dark gray into light gray and our light gray into white.
    `im` must already be quantized to 0/85/170/255.
    """
    w, h = im.size
    row_bytes = (w * 2 + 31) // 32 * 4
    px = im.load()
    rows = bytearray()
    for y in range(h - 1, -1, -1):  # bottom-up
        row = bytearray(row_bytes)
        for x in range(w):
            level = min(3, round(px[x, y] / 85))
            row[x >> 2] |= level << (6 - (x & 3) * 2)
        rows += row
    palette = b"".join(bytes((g, g, g, 0)) for g in (0, 85, 170, 255))
    off = 14 + 40 + len(palette)
    header = b"BM" + struct.pack("<IHHI", off + len(rows), 0, 0, off)
    info = struct.pack("<IiiHHIIiiII", 40, w, h, 1, 2, 0, len(rows), 9370, 9370, 4, 4)
    path.write_bytes(header + info + palette + rows)


def contact_sheet(images: list[Image.Image], path: Path, cols: int = 5, t: float = 0.4) -> None:
    w, h = images[0].size
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
    ref_h = device.get("reference_height", 2000)
    for sub in ("2bpp", f"gray-{ref_h}", "preview"):
        (OUT / sub).mkdir(parents=True, exist_ok=True)

    built = []
    for e in entries:
        if not (CACHE / e["patent"] / "meta.json").exists():
            print(f"{e['patent']}: not cached, run src/fetch.py first")
            continue
        name, gray = build_one(e, device, style)
        im = quantize(gray, device["levels"])
        save_bmp_2bpp(im, OUT / "2bpp" / f"{name}.bmp")
        _, ref = build_one(e, device, style, height=ref_h)
        ref.save(OUT / f"gray-{ref_h}" / f"{name}.png", optimize=True)
        im.save(OUT / "preview" / f"{name}.png", optimize=True)
        built.append(im)
        print(f"built {name}")
    if built and not argv:
        contact_sheet(built, OUT / "contact-sheet.png")
        print(f"{len(built)} wallpapers -> {OUT}")


if __name__ == "__main__":
    main(sys.argv[1:])
