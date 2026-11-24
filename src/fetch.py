"""Download patent metadata and full-size drawing sheets from Google Patents.

Usage:
    python src/fetch.py                 # fetch every patent listed in patents.toml
    python src/fetch.py US730918 US11942  # fetch (or preview) arbitrary patent numbers

Each patent is cached under cache/<number>/ as:
    meta.json        title, dates, inventors, list of sheet files
    sheet-00.png...  full-resolution drawing sheets (sheet-00 is usually the front-page figure)
"""
from __future__ import annotations

import html
import json
import re
import sys
import time
import tomllib
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "cache"
UA = "Mozilla/5.0 (Macintosh) patent-wallpapers/1.0"


def get(url: str) -> bytes:
    # Google Patents answers Python's urllib with 503s, so shell out to curl.
    for attempt in range(4):
        r = subprocess.run(
            ["curl", "-sSL", "--fail", "-A", UA, "--max-time", "60", url],
            capture_output=True,
        )
        if r.returncode == 0:
            return r.stdout
        if attempt < 3:
            time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"curl failed for {url}: {r.stderr.decode().strip()}")


def first(pattern: str, text: str) -> str | None:
    m = re.search(pattern, text, re.S)
    return html.unescape(m.group(1)).strip() if m else None


def fetch(number: str, force: bool = False) -> dict:
    out = CACHE / number
    meta_path = out / "meta.json"
    if meta_path.exists() and not force:
        return json.loads(meta_path.read_text())

    page = get(f"https://patents.google.com/patent/{number}/en").decode("utf-8", "replace")
    title = first(r"<title>[^-]*-\s*(.*?)\s*-\s*Google Patents</title>", page) or ""
    meta = {
        "number": number,
        "title": re.sub(r"\s+", " ", title),
        "publication_date": first(r'itemprop="publicationDate"[^>]*>([^<]+)', page),
        "priority_date": first(r'itemprop="priorityDate"[^>]*>([^<]+)', page),
        "inventors": [html.unescape(x).strip() for x in re.findall(r'itemprop="inventor"[^>]*>([^<]+)', page)],
        "url": f"https://patents.google.com/patent/{number}/en",
        "sheets": [],
    }
    fulls = re.findall(r'<meta itemprop="full" content="([^"]+\.png)"', page)
    out.mkdir(parents=True, exist_ok=True)
    for i, url in enumerate(dict.fromkeys(fulls)):  # de-dupe, keep order
        name = f"sheet-{i:02d}.png"
        (out / name).write_bytes(get(url))
        meta["sheets"].append(name)
        time.sleep(0.3)
    meta_path.write_text(json.dumps(meta, indent=2))
    return meta


def main(argv: list[str]) -> None:
    if argv:
        numbers = argv
    else:
        cfg = tomllib.loads((ROOT / "patents.toml").read_text())
        numbers = [w["patent"] for w in cfg["wallpaper"]]
    for n in numbers:
        try:
            m = fetch(n)
            print(f"{n:<12} {len(m['sheets']):>2} sheets  {m['priority_date'] or '?':<10}  {m['title']}")
        except Exception as e:  # keep going on bad numbers
            print(f"{n:<12} FAILED: {e}")
        time.sleep(1)


if __name__ == "__main__":
    main(sys.argv[1:])
