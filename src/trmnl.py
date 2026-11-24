"""Render the wallpaper set for the TRMNL e-ink display (original model, 800x480,
4 grays), one image per TRMNL layout.

The images go to TRMNL's Image Display plugin, which scales and dithers every
image itself. So they are full grayscale (pre-quantized pixels just get
re-dithered into speckle) and rendered at `supersample` x the slot size (TRMNL
scales down more cleanly than up). Midtones are darkened by `gamma` so thin
lines stay solid after TRMNL's dithering.

Usage:
    python src/trmnl.py              # build everything in patents.toml
    python src/trmnl.py US730918A    # build only the listed patents

Layouts and their sizes come from [trmnl.<layout>] in patents.toml. The mashup
slot sizes follow TRMNL's framework CSS on an 800x480 screen with its 10 px gap:
full 800x480, half_vertical 385x460, half_horizontal 780x225, quadrant 385x225.

Each layout picks, per drawing, whichever arrangement it allows that shows the
drawing largest: "stack" (caption under the drawing) or "side" (caption in a
column beside it, on the left by default).

Output:
    output/trmnl/<layout>/<slug>.png   8-bit grayscale PNG, supersample x slot size
    output/trmnl/contact-<layout>.png  contact sheet per layout, for review
"""
from __future__ import annotations

import json
import math
import sys
import tomllib
from pathlib import Path

from PIL import Image, ImageDraw

from build import (CACHE, OUT, ROOT, caption_block, caption_text, clean_drawing, contact_sheet, fit_drawing,
                   font, set_title, slug)

TRMNL_OUT = OUT / "trmnl"
# Layout keys measured in pixels; these scale with `supersample`.
PIXEL_KEYS = {"width", "height", "margin", "header_size", "title_size", "title_min_size", "inventor_size",
              "caption_gap", "rule_gap", "line_gap", "side_line_gap", "title_nudge", "header_nudge",
              "rule_width", "side_gap", "side_min", "side_max"}


def scaled(st: dict, k: int) -> dict:
    out = {key: (v * k if key in PIXEL_KEYS else v) for key, v in st.items()}
    out["rule_thickness"] = k
    return out


def darken(im: Image.Image, gamma: float) -> Image.Image:
    """Darken midtones (v -> 255 * (v/255)^gamma); black and white stay put."""
    return im.point([round(255 * (v / 255) ** gamma) for v in range(256)])


def side_min_width(meta: dict, entry: dict, st: dict, limit: int) -> int:
    """Narrowest caption column (at least `side_min`) that keeps the header on one
    line (when `header_wrap` is false) and the title within `max_title_lines`."""
    header, _, _, title, _ = caption_text(meta, entry, st)
    w = st["side_min"]
    if st.get("show_header", True) and not st.get("header_wrap", True):
        w = max(w, math.ceil(font("regular", st["header_size"]).getlength(header)) + 2)
    max_lines = st.get("max_title_lines", 2)
    while w < limit:
        size, lines = set_title(title, st["title_size"], st.get("title_min_size", 16), w, max_lines)
        if len(lines) <= max_lines and max(font("italic", size).getlength(l) for l in lines) <= w:
            break
        w += 4
    return min(w, limit)


def compose(clean: Image.Image, entry: dict, meta: dict, st: dict, supersample: int = 1) -> Image.Image:
    W, H, m = st["width"], st["height"], st["margin"]
    arrangements = st.get("arrangements", ["stack", "side"])
    options = []  # (score, kind, box_w, box_h, cap_w, cap_h, draw_caption)

    if "stack" in arrangements:
        cap_h, draw = caption_block(meta, entry, st, W - 2 * m)
        bw, bh = W - 2 * m, H - 2 * m - cap_h - st["caption_gap"]
        if bh > 0:
            options.append((min(bw / clean.width, bh / clean.height), "stack", bw, bh, W - 2 * m, cap_h, draw))

    if "side" in arrangements:
        sst = {**st, "line_gap": st.get("side_line_gap", st["line_gap"])}  # airier column caption
        g, bh = st["side_gap"], H - 2 * m
        # Give the drawing its natural width at full height; the caption column
        # takes what's left, within [side_min, side_max] but never narrower than
        # its text needs.
        need = side_min_width(meta, entry, sst, W * 3 // 5)
        natural_w = clean.width * bh / clean.height
        cap_w = round(max(need, min(st["side_max"], max(st["side_min"], W - 2 * m - g - natural_w))))
        bw = W - 2 * m - g - cap_w
        cap_h, draw = caption_block(meta, entry, sst, cap_w)
        if cap_h <= bh and bw > 0:
            score = min(bw / clean.width, bh / clean.height) * st.get("side_bias", 1.0)
            options.append((score, "side", bw, bh, cap_w, cap_h, draw))

    if not options:
        raise ValueError(f"{entry['patent']}: caption doesn't fit the {W}x{H} layout")
    _, kind, bw, bh, cap_w, cap_h, draw_caption = max(options, key=lambda o: o[0])
    drawing = fit_drawing(clean, entry, bw, bh, supersample)

    canvas = Image.new("L", (W, H), 255)
    d = ImageDraw.Draw(canvas)
    if kind == "stack":
        gap = st["caption_gap"]
        if st.get("stack_anchor") == "bottom":
            # E-reader style: caption pinned at the bottom margin, drawing
            # centred in the space above it.
            cap_y = H - m - cap_h
            top = m + (cap_y - gap - m - drawing.height) // 2
        else:  # drawing + caption centred together
            top = (H - drawing.height - gap - cap_h) // 2
            cap_y = top + drawing.height + gap
        canvas.paste(drawing, ((W - drawing.width) // 2, top))
        draw_caption(d, m, cap_y)
    else:
        # Spread spare width evenly over the two outer margins and the gap
        # (gap never below side_gap), so the pair doesn't huddle mid-frame.
        g, spare = st["side_gap"], W - drawing.width - cap_w
        if spare / 3 >= max(g, m):
            outer = gap = spare // 3
        else:
            gap, outer = g, (spare - g) // 2
        dy, cy = (H - drawing.height) // 2, (H - cap_h) // 2
        if st.get("caption_side", "left") == "left":
            draw_caption(d, outer, cy)
            canvas.paste(drawing, (outer + cap_w + gap, dy))
        else:
            canvas.paste(drawing, (outer, dy))
            draw_caption(d, outer + drawing.width + gap, cy)
    return canvas


def main(argv: list[str]) -> None:
    cfg = tomllib.loads((ROOT / "patents.toml").read_text())
    trmnl = cfg["trmnl"]
    layouts = {name: {**trmnl.get("style", {}), **st} for name, st in trmnl.items()
               if isinstance(st, dict) and "width" in st}
    entries = [e for e in cfg["wallpaper"] if not argv or e["patent"] in argv]
    for name in layouts:
        (TRMNL_OUT / name).mkdir(parents=True, exist_ok=True)

    ss, gamma = trmnl.get("supersample", 2), trmnl.get("gamma", 1.7)
    built: dict[str, list[Image.Image]] = {name: [] for name in layouts}
    for e in entries:
        meta_path = CACHE / e["patent"] / "meta.json"
        if not meta_path.exists():
            print(f"{e['patent']}: not cached, run src/fetch.py first")
            continue
        meta = json.loads(meta_path.read_text())
        clean = clean_drawing(CACHE / e["patent"] / f"sheet-{e.get('sheet', 0):02d}.png", e)
        name = slug(meta, e)
        for layout, st in layouts.items():
            im = darken(compose(clean, e, meta, scaled(st, ss), ss), gamma)
            im.save(TRMNL_OUT / layout / f"{name}.png", optimize=True)
            built[layout].append(im)
        print(f"built {name}")

    if not argv:
        for layout, ims in built.items():
            if ims:
                contact_sheet(ims, TRMNL_OUT / f"contact-{layout}.png", cols=4,
                              t=(0.5 if ims[0].width > 600 * ss else 1.0) / ss)
        print(f"{len(entries)} patents x {len(layouts)} layouts -> {TRMNL_OUT}")


if __name__ == "__main__":
    main(sys.argv[1:])
