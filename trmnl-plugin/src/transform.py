"""Serverless transform: pick the patent to show on this refresh.

TRMNL polls manifest.json (built by src/plugin.py and served from GitHub
Pages) and calls run(input) with its JSON merged at the top level, plus the
`trmnl` namespace. run() returns the merge variables for one patent. TRMNL
only draws a new screen when the merge variables change, which is why the
pick happens here and not in the markup: `pick_id` goes up on every run, so
even a one-patent set redraws.

Saved state (input.trmnl.state, written back through the `trmnl_state` key,
8 KB at most) keeps each plugin instance's own queue:
    q     patent ids still to show in this pass, in order
    seen  `added` time of the newest patent already featured as new
    last  id shown last, so a reshuffle never starts with it
    n     pick counter, returned as pick_id

Order: patents added since `seen` go first, oldest first, one per refresh.
Otherwise take the next id in the queue, refilling it with a fresh shuffle
of every patent when it runs out. On the first run `seen` starts at now, so
the back catalogue isn't treated as new.

No `from __future__` and no new-style annotations: TRMNL wraps this file
in its own runner, and its Python version isn't documented.
"""
import json
import random
from datetime import datetime, timezone

MANIFEST_URL = "https://johnlago.github.io/patent-wallpapers/plugin/manifest.json"
STATE_LIMIT = 8000  # bytes; TRMNL ignores a trmnl_state over 8192


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def manifest_from(data):
    """The polled manifest: at the top level with one polling URL, under
    IDX_0 with several. If the poll brought nothing, fetch it directly."""
    for candidate in (data, data.get("IDX_0")):
        if isinstance(candidate, dict) and isinstance(candidate.get("patents"), list) and candidate["patents"]:
            return candidate
    try:
        import requests
        fetched = requests.get(MANIFEST_URL, timeout=3).json()
        if isinstance(fetched.get("patents"), list) and fetched["patents"]:
            return fetched
    except Exception:  # noqa: BLE001 - any failure means "no manifest"
        pass
    return None


def choose(patents, state, rng, now):
    """(patent, new state, is_new) for one refresh."""
    by_id = {p["id"]: p for p in patents}
    ids = list(by_id)
    seen = state.get("seen") or now
    last = state.get("last")
    queue = [i for i in state.get("q", []) if i in by_id]

    fresh = sorted((p for p in patents if p.get("added") and p["added"] > seen), key=lambda p: (p["added"], p["id"]))
    if fresh:
        pick, is_new = fresh[0], True
        seen = pick["added"]
        queue = [i for i in queue if i != pick["id"]]
    else:
        if not queue:
            queue = ids[:]
            rng.shuffle(queue)
            if len(queue) > 1 and queue[0] == last:  # no repeat across the reshuffle
                j = rng.randrange(1, len(queue))
                queue[0], queue[j] = queue[j], queue[0]
        pick, is_new = by_id[queue.pop(0)], False

    new_state = {"q": queue, "seen": seen, "last": pick["id"], "n": int(state.get("n", 0)) + 1}
    while len(json.dumps(new_state, separators=(",", ":"))) > STATE_LIMIT and new_state["q"]:
        new_state["q"] = new_state["q"][: len(new_state["q"]) * 3 // 4]  # rest come back next pass
    return pick, new_state, is_new


def run(input):  # noqa: A002 - TRMNL's name for it
    data = input if isinstance(input, dict) else {}
    trmnl = data.get("trmnl") or {}
    state = trmnl.get("state") or {}
    manifest = manifest_from(data)
    if not manifest:
        # Nothing to show; leave state alone so the queue survives an outage.
        return {"error": "Patent drawings are unavailable right now."}

    pick, new_state, is_new = choose(manifest["patents"], state if isinstance(state, dict) else {},
                                     random.Random(), now_iso())
    base = manifest.get("base_url") or MANIFEST_URL.rsplit("/", 1)[0] + "/"
    return {
        "id": pick["id"],
        "number": pick["number"],
        "year": pick.get("year", ""),
        "title": pick["title"],
        "inventors": pick.get("inventors", ""),
        "image_url": base + pick["image"],
        "aspect": pick.get("aspect", 1),
        "L": pick["layouts"],
        "R": manifest.get("layouts", {}),
        "is_new": is_new,
        "pick_id": new_state["n"],
        "trmnl_state": new_state,
    }
