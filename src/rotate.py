"""Assemble the GitHub Pages site that TRMNL's Image Display plugin reads: one
"current" image per layout, at a fixed URL that changes what it serves over time.

Usage:
    python src/rotate.py [site_dir]      # default: site/

Writes:
    <site>/current/<layout>.png   the image for this time slot, per layout
    <site>/current.json           which patent each layout is showing, and when
    <site>/index.html             a small page showing all four

Picks are stateless and deterministic: time is cut into slots of
INTERVAL_HOURS, and each layout walks its own shuffled order of the whole set,
reshuffled every time it has shown everything. So a run at any point in a slot
(scheduled or triggered by a push) serves the same images, and nothing repeats
until the set is exhausted. Each layout has its own order, so a mashup shows
different patents side by side.

Standard library only, so the GitHub Action needs no installs.
"""
from __future__ import annotations

import html
import json
import random
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TRMNL = ROOT / "output" / "trmnl"
LAYOUTS = ["full", "half_vertical", "half_horizontal", "quadrant"]
INTERVAL_HOURS = 6  # keep in step with the cron schedule in .github/workflows/trmnl.yml


def pick(names: list[str], layout: str, slot: int) -> str:
    n = len(names)
    cycle, pos = divmod(slot, n)
    order = sorted(names)
    random.Random(f"{layout}:{n}:{cycle}").shuffle(order)
    return order[pos]


def main(argv: list[str]) -> None:
    site = Path(argv[0]) if argv else ROOT / "site"
    if site.exists():
        shutil.rmtree(site)
    (site / "current").mkdir(parents=True)

    now = time.time()
    slot = int(now // (INTERVAL_HOURS * 3600))
    current = {"generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
               "interval_hours": INTERVAL_HOURS, "layouts": {}}
    for layout in LAYOUTS:
        names = [p.stem for p in (TRMNL / layout).glob("*.png")]
        if not names:
            sys.exit(f"no images in {TRMNL / layout}; run `make trmnl` first")
        name = pick(names, layout, slot)
        shutil.copyfile(TRMNL / layout / f"{name}.png", site / "current" / f"{layout}.png")
        current["layouts"][layout] = name
        print(f"{layout:16} {name}")

    (site / "current.json").write_text(json.dumps(current, indent=2) + "\n")
    figures = "\n".join(
        f'<figure><img src="current/{l}.png" alt="{html.escape(n)}">'
        f'<figcaption><code>current/{l}.png</code> &middot; {html.escape(n)}</figcaption></figure>'
        for l, n in current["layouts"].items())
    (site / "index.html").write_text(f"""<!doctype html>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Patent wallpapers for TRMNL</title>
<style>
  body {{ font: 15px/1.5 Georgia, serif; margin: 2rem auto; max-width: 860px; padding: 0 1rem; color: #222; }}
  figure {{ margin: 0 0 2rem; }}
  img {{ border: 1px solid #ccc; max-width: 100%; image-rendering: pixelated; }}
  figcaption {{ color: #666; font-size: 13px; }}
</style>
<h1>Patent wallpapers for TRMNL</h1>
<p>Current images, rotated every {INTERVAL_HOURS} hours. Updated {current["generated"]}.</p>
{figures}
""")


if __name__ == "__main__":
    main(sys.argv[1:])
