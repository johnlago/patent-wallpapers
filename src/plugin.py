"""Build the data for the native TRMNL plugin ("Patent of the Moment").

Usage:
    python src/plugin.py                      # build everything in patents.toml
    python src/plugin.py stamp <src> <dest>   # copy a built output/plugin/ to <dest>,
                                              # dating each patent from git history
    python src/plugin.py contact              # contact sheets from the trmnlp screens
                                              # in output/plugin-preview/ (make plugin-contact)

Writes output/plugin/:
    drawings/<slug>.png  the drawing only, no caption: cleaned like every other
                         set, long side 1600 px, lines thickened for a ~400 px
                         display size, midtones darkened, 16 grays (4-bit PNG)
    fonts/               Libron (OFL) woff2 files the plugin's markup loads
    manifest.json        one entry per patent: caption text, image path, aspect,
                         when it was added, and a layout plan per TRMNL layout

The plugin's serverless transform (trmnl-plugin/src/transform.py) polls the
manifest, picks one patent per refresh and hands that entry to the Liquid
markup. Each layout plan is decided here, with the same rules and the same
caption metrics as the Image Display set (src/trmnl.py's `plan`), but measured
in Libron, the typeface the plugin renders with. The markup just places the
boxes and sets the text, sized in proportion to the slot.

`stamp` is standard library only: the Pages workflow runs it on a runner with
no Pillow. It needs full git history (fetch-depth: 0) to date patents; any it
can't date get the time of the run, so they count as new.
"""
from __future__ import annotations

import json
import shutil
import sys
import time
import tomllib
from pathlib import Path

from rotate import added_times

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "output" / "plugin"
FONTS = ROOT / "fonts" / "libron"
BASE_URL = "https://johnlago.github.io/patent-wallpapers/plugin/"
LONG_SIDE = 1600      # px, long side of each drawing PNG
DISPLAY_SIZE = 400    # px, roughly how large a drawing shows; sets line thickening
MAX_DRAWING_BYTES = 200_000


def iso(t: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))


def stamp(manifest: dict) -> dict:
    """Fill in each patent's `added` from git: when its TRMNL image was first
    committed (the same history src/rotate.py reads). Undated patents, such as
    ones built but not yet committed, get the current time."""
    added, now = added_times(), time.time()
    for p in manifest["patents"]:
        p["added"] = iso(added.get(p["slug"], now))
    return manifest


def layout_style(st: dict) -> dict:
    """What the markup needs from a [trmnl.<layout>] table: slot size (w, h),
    header / inventor sizes (hs, is), the gap between caption lines in stacked
    and side captions (lg, slg), and the divider rule (rule, rg = gap below it,
    rw = half its width)."""
    return {"w": st["width"], "h": st["height"], "hs": st["header_size"], "is": st["inventor_size"],
            "lg": st["line_gap"], "slg": st.get("side_line_gap", st["line_gap"]),
            "rule": bool(st.get("show_header", True) and st.get("show_rule", True)),
            "rg": st.get("rule_gap", 0), "rw": st.get("rule_width", 36)}


def plan_layouts(clean, entry: dict, meta: dict, layouts: dict) -> dict:
    """Per-layout plan for the markup, in the layout's own pixels at 1x:
    a = arrangement, d = drawing box [x, y, w, h], c = caption box [x, y, w, h],
    h = patent-number line(s), t = title lines, ts = title size, i = inventor lines."""
    from build import caption_text, font, set_title, wrap
    from trmnl import plan

    out = {}
    for name, st in layouts.items():
        p = plan(clean, entry, meta, st)
        used = p["style"]
        header, number, year, title, inventor = caption_text(meta, entry, used)
        # Same choices caption_block makes for the header and title.
        hl = [header]
        if used.get("header_wrap", True) and font("regular", used["header_size"]).getlength(header) > p["cap_w"]:
            hl = [number] + ([year] if year else [])
        ts, tl = set_title(title, used["title_size"], used.get("title_min_size", 16), p["cap_w"],
                           used.get("max_title_lines", 2))
        (dx, dy), (cx, cy) = p["drawing_xy"], p["caption_xy"]
        out[name] = {"a": p["kind"], "d": [dx, dy, p["drawing"].width, p["drawing"].height],
                     "c": [cx, cy, p["cap_w"], p["cap_h"]], "h": hl, "t": tl, "ts": ts,
                     "i": wrap(inventor, font("regular", used["inventor_size"]), p["cap_w"]) if inventor else []}
    return out


def make(argv: list[str]) -> None:
    import build as b
    from build import CACHE, caption_text, clean_drawing, fit_drawing, pretty_number, slug
    from PIL import Image
    from trmnl import darken

    # Measure captions in the typeface the plugin renders with.
    b.FONT_CANDIDATES = {"regular": [str(FONTS / "Libron-Regular.ttf")],
                         "italic": [str(FONTS / "Libron-Italic.ttf")]}
    cfg = tomllib.loads((ROOT / "patents.toml").read_text())
    trmnl = cfg["trmnl"]
    overrides = cfg.get("plugin", {})  # [plugin.<layout>]: plugin-only tweaks to [trmnl.<layout>]
    layouts = {name: {**trmnl.get("style", {}), **st, **overrides.get(name, {}), "rule_thickness": 1}
               for name, st in trmnl.items() if isinstance(st, dict) and "width" in st}
    gamma = trmnl.get("gamma", 1.7)
    entries = [e for e in cfg["wallpaper"] if not argv or e["patent"] in argv]

    (OUT / "drawings").mkdir(parents=True, exist_ok=True)
    (OUT / "fonts").mkdir(parents=True, exist_ok=True)
    for f in FONTS.glob("*.woff2"):
        shutil.copyfile(f, OUT / "fonts" / f.name)
    for f in ("LICENSE", "COPYRIGHT"):
        shutil.copyfile(FONTS / f, OUT / "fonts" / f)

    old = {}
    if argv and (OUT / "manifest.json").exists():  # partial build: keep the other entries
        old = {p["slug"]: p for p in json.loads((OUT / "manifest.json").read_text())["patents"]}

    patents = []
    for e in cfg["wallpaper"]:
        meta_path = CACHE / e["patent"] / "meta.json"
        if not meta_path.exists():
            print(f"{e['patent']}: not cached, run src/fetch.py first")
            continue
        meta = json.loads(meta_path.read_text())
        name = slug(meta, e)
        if e not in entries:
            if name in old:
                patents.append(old[name])
            continue
        clean = clean_drawing(CACHE / e["patent"] / f"sheet-{e.get('sheet', 0):02d}.png", e)
        k = LONG_SIDE / max(clean.size)
        drawing = darken(fit_drawing(clean, e, round(clean.width * k), round(clean.height * k),
                                     supersample=LONG_SIDE // DISPLAY_SIZE), gamma)
        path = OUT / "drawings" / f"{name}.png"
        # 16 grays, as many as any TRMNL panel shows: a 4-bit PNG is about half the size.
        drawing.point(lambda v: round(v / 17) * 17).quantize(16, dither=Image.Dither.NONE).save(
            path, optimize=True, bits=4)
        if path.stat().st_size > MAX_DRAWING_BYTES:
            print(f"  warning: {path.name} is {path.stat().st_size // 1000} KB")
        _, _, year, title, inventors = caption_text(meta, e, layouts["full"])
        patents.append({
            "id": name.split("-")[0],
            "slug": name,
            "number": pretty_number(meta["number"]),
            "year": year,
            "title": title,
            "inventors": inventors,
            "image": f"drawings/{name}.png",
            "aspect": round(drawing.width / drawing.height, 3),
            "layouts": plan_layouts(clean, e, meta, layouts),
        })
        print(f"built {name}")

    ids = [p["id"] for p in patents]
    if len(set(ids)) != len(ids):
        sys.exit(f"duplicate patent ids: {sorted(i for i in set(ids) if ids.count(i) > 1)}")
    keep = {f"{p['slug']}.png" for p in patents}
    for f in (OUT / "drawings").glob("*.png"):
        if f.name not in keep:
            f.unlink()
    manifest = stamp({"version": 1, "generated": iso(time.time()), "base_url": BASE_URL,
                      "layouts": {n: layout_style(st) for n, st in layouts.items()},
                      "patents": patents})
    text = json.dumps(manifest, ensure_ascii=False, separators=(",", ":"))
    (OUT / "manifest.json").write_text(text + "\n")
    print(f"{len(patents)} patents -> {OUT} (manifest {len(text) // 1000} KB)")


def stamp_copy(src: Path, dest: Path) -> None:
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest)
    manifest = stamp(json.loads((src / "manifest.json").read_text()))
    (dest / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, separators=(",", ":")) + "\n")
    print(f"{len(manifest['patents'])} patents -> {dest}")


def contact(preview: Path = ROOT / "output" / "plugin-preview") -> None:
    """One contact sheet per layout from the screens trmnlp rendered (tests/plugin_spec.rb
    writes <layout>/<slug>.png, the whole 800x480 screen, and <slug>.json, the slot's box),
    in manifest order, cropped to the slot, like output/trmnl/contact-*.png."""
    from PIL import Image
    from build import contact_sheet

    slugs = [p["slug"] for p in json.loads((OUT / "manifest.json").read_text())["patents"]]
    for d in sorted(x for x in preview.iterdir() if x.is_dir()):
        ims = []
        for name in slugs:
            if not (d / f"{name}.png").exists():
                continue
            box = json.loads((d / f"{name}.json").read_text())
            ims.append(Image.open(d / f"{name}.png").convert("L").crop(
                tuple(round(box[k]) for k in ("left", "top", "right", "bottom"))))
        if ims:
            contact_sheet(ims, preview / f"contact-{d.name}.png", cols=4, t=0.5 if ims[0].width > 600 else 1.0)
            print(f"{len(ims)} screens -> {preview / f'contact-{d.name}.png'}")


if __name__ == "__main__":
    if sys.argv[1:2] == ["stamp"]:
        stamp_copy(Path(sys.argv[2]), Path(sys.argv[3]))
    elif sys.argv[1:2] == ["contact"]:
        contact()
    else:
        make(sys.argv[1:])
