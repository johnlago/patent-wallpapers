"""Assemble the GitHub Pages site that TRMNL's Image Display plugin reads: one
"current" image per layout, at a fixed URL that changes what it serves over time.

Usage:
    python src/rotate.py [site_dir]      # default: site/

Writes:
    <site>/current/<layout>.png   the image for this time slot, per layout
    <site>/current.json           which patent each layout is showing, and when
    <site>/index.html             a small page showing all four

Picks are stateless and deterministic: time is cut into slots of
INTERVAL_HOURS (slot = Unix time // interval), and each layout walks its own
shuffled order of the whole set, reshuffled every time it has shown everything.
So a run at any point in a slot (scheduled or triggered by a push) serves the
same images, and nothing repeats until the set is exhausted. Each layout has
its own order, so a mashup shows different patents side by side.

New patents jump the queue. The commit that first added a patent's image
(read from git history) sets its "featured" start slot: the slot it was pushed
in, so it appears right away. It shows in `full` in that slot, then
`half_vertical` in the next, and so on: once in each layout over a day, never
in two layouts at once. Patents added together are staggered one slot apart.
A new patent is kept out of the shuffle until one full cycle after its run
starts, so it isn't shown early or again soon after.
Only patents added after NEW_AFTER count (the original set isn't "new").

Standard library only, so the GitHub Action needs no installs. It does need
full git history (fetch-depth: 0); without it, nothing is featured.
"""
from __future__ import annotations

import html
import json
import random
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TRMNL = ROOT / "output" / "trmnl"
LAYOUTS = ["full", "half_vertical", "half_horizontal", "quadrant"]
INTERVAL_HOURS = 6  # keep in step with the cron schedule in .github/workflows/trmnl.yml
INTERVAL = INTERVAL_HOURS * 3600
# Patents whose images were first committed after this are featured as new.
NEW_AFTER = datetime.fromisoformat("2026-11-24T23:15:00+00:00").timestamp()


def added_times() -> dict[str, int]:
    """Unix time of the commit that first added each patent's image, from git."""
    try:
        out = subprocess.run(
            ["git", "log", "--diff-filter=A", "--format=%x00%ct", "--name-only", "--", "output/trmnl/full/"],
            cwd=ROOT, capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return {}
    added: dict[str, int] = {}
    for block in out.split("\0")[1:]:  # newest commit first
        lines = block.split()
        if not lines:
            continue
        for path in lines[1:]:
            added[Path(path).stem] = int(lines[0])  # later (older) commits overwrite: keeps the first add
    return added


def feature_starts(added: dict[str, int], names: set[str]) -> dict[str, int]:
    """Start slot for each patent added after NEW_AFTER: the slot it was added
    in, pushed back as needed so starts are one slot apart."""
    starts, prev = {}, None
    for t, name in sorted((t, n) for n, t in added.items() if t > NEW_AFTER and n in names):
        start = t // INTERVAL if prev is None else max(t // INTERVAL, prev + 1)
        starts[name] = prev = start
    return starts


def pick(names: list[str], layout: str, slot: int, starts: dict[str, int] | None = None) -> str:
    starts = starts or {}
    i = LAYOUTS.index(layout)
    for name, start in starts.items():  # featured: full at start, half_vertical at start+1, ...
        if start + i == slot:
            return name
    n = len(names)
    # Keep featured patents out of the shuffle from now until one full cycle
    # after their run starts, so they don't turn up early or again too soon.
    busy = {name for name, start in starts.items() if slot < start + max(len(LAYOUTS), n)}
    cycle, pos = divmod(slot, n)
    order = sorted(names)
    random.Random(f"{layout}:{n}:{cycle}").shuffle(order)
    if order[pos] not in busy:
        return order[pos]
    # The shuffle landed on a featured patent: borrow one from halfway around the
    # order, far from the neighbouring slots, so the stand-in isn't shown twice in a row.
    for k in range(n):
        alt = order[(pos + n // 2 + k) % n]
        if alt not in busy:
            return alt
    return order[pos]


def main(argv: list[str]) -> None:
    site = Path(argv[0]) if argv else ROOT / "site"
    if site.exists():
        shutil.rmtree(site)
    (site / "current").mkdir(parents=True)

    now = time.time()
    slot = int(now // INTERVAL)
    names_all = {p.stem for p in (TRMNL / "full").glob("*.png")}
    added = added_times()
    starts = feature_starts(added, names_all)
    print(f"{len(added)} of {len(names_all)} patents dated from git history; {len(starts)} added since NEW_AFTER")
    current = {"generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
               "interval_hours": INTERVAL_HOURS, "layouts": {}}
    for layout in LAYOUTS:
        names = [p.stem for p in (TRMNL / layout).glob("*.png")]
        if not names:
            sys.exit(f"no images in {TRMNL / layout}; run `make trmnl` first")
        name = pick(names, layout, slot, starts)
        shutil.copyfile(TRMNL / layout / f"{name}.png", site / "current" / f"{layout}.png")
        current["layouts"][layout] = name
        print(f"{layout:16} {name}" + ("  (new)" if name in starts and starts[name] <= slot else ""))

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
