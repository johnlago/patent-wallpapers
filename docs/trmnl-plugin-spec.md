# Spec: "Patent of the Moment", a native TRMNL plugin

Status: built 2026-11-24 (see §9 for what the verification spike found and
what changed from the proposal). Written 2026-11-24.

## 1. Goal

Turn the patent wallpapers into a real TRMNL plugin (a private plugin you can
later publish as a Recipe) that shows **a different patent on every plugin
refresh**. It must work in all four TRMNL layouts (full, half_horizontal,
half_vertical, quadrant) and on any TRMNL model, with captions TRMNL renders as
real text.

### Why change what works today

Today a GitHub Action publishes pre-rendered images to GitHub Pages every 6
hours, and four **Image Display** plugins point at them (see the README, "TRMNL"
section). That has four limits:

1. **Rotation speed.** Rotation is tied to a GitHub cron job, not to the
   plugin's refresh. GitHub cron is coarse and unreliable, and each change
   needs a Pages deploy.
2. **Double processing.** TRMNL rescales and re-dithers our finished images,
   caption text included.
3. **Fixed sizes.** Layouts are hard-coded to the original TRMNL's 800×480
   slot sizes. A TRMNL X or other device gets crops or blur.
4. **No per-device rotation.** Every viewer sees the same image, and avoiding
   repeats relies on time-slot arithmetic instead of real "seen" tracking.

## 2. What TRMNL gives us (from the docs, 2026-11)

Quoted or summarized from docs.trmnl.com and help.trmnl.com. Items marked
**VERIFY** are undocumented or unconfirmed: check them first (see §8).

- **Private plugins** have four markup tabs (Full, Half Horizontal, Half
  Vertical, Quadrant) plus a **Shared** tab prepended to each. They use Shopify
  Liquid plus TRMNL filters (`random_number`, `sample`, `parse_json`,
  `where_exp`, …). Partials use `{% template %}` and `{% render %}`.
- **Rendering**: "We load your markup in a real browser, wait for it, then take
  a screenshot." The page has about 5 s to load. The output is quantized to the
  device's bit depth: 1-bit or 2-bit on the original TRMNL, 4-bit on the X.
  External `<img>`, `<style>` and `<link>` are allowed. Fonts come from
  `plugins.css`, and framework 3.4 has a "Custom Typefaces" page (**VERIFY**
  how). There is a "Remove Bleed Margin" option for edge-to-edge images.
- **Data strategies**:
  - **Polling**: one or more URLs, GET or POST, custom headers. TRMNL fetches
    them on the plugin's refresh rate (15 min default, 5 min on TRMNL+;
    "Fastest Refresh Rate" sets the minimum installers can pick).
  - **Webhook**: POST merge variables, at most 12 per hour and 5 KB (30 per
    hour and 10 KB on TRMNL+).
- **Serverless transform**: a `run(input)` function in Python, Node 20, Ruby or
  PHP, with network access, 128 MB and 5 s. It receives the polled data plus
  `trmnl.*` and custom-field values, and returns the merge variables. Output
  must fit 5 KB (10 KB on TRMNL+). **`trmnl.state`** is "data your Serverless
  transform saved for the next refresh" (**VERIFY** the exact read/write API
  on the "Saved State" help article, 16777795).
- **Re-render rule (critical)**: "When a plugin refreshes and its data hasn't
  changed, TRMNL keeps the screen it already has and doesn't render a new one."
  So **randomness in Liquid alone does nothing**. The merge variables must
  change on every refresh, so the patent must be chosen in the data step.
- **Form fields** (`settings.yml` custom fields): `select`, `number`,
  `boolean`, … These are readable in markup, the polling URL and the transform.
- **Variables**: `trmnl.device.width/height`, `trmnl.user.*`,
  `trmnl.plugin_settings.*`, `trmnl.system.timestamp_utc`, `"now" | date`.
- **Tooling**: `trmnlp` (github.com/usetrmnl/trmnlp) is a local dev server. It
  provides `serve`, `build --png`, `lint`, `test` (fixed clock), and
  `push`/`pull` to the account. The project layout is `src/settings.yml`,
  `src/{full,half_horizontal,half_vertical,quadrant,shared}.liquid`, plus
  `.trmnlp.yml`, where `asset_overrides` can point image URLs at local files.
- **Recipes**: publish from plugin settings after review. Installs get updates
  automatically; forks don't. Installers' custom-field values aren't copied.

## 3. Architecture

```
 repo (build pipeline)              GitHub Pages (static CDN)         TRMNL
 ─────────────────────              ─────────────────────────         ─────
 make plugin  ──────────▶  /plugin/manifest.json   ◀── poll ──  private plugin
   drawings + metadata     /plugin/drawings/<slug>.png              │
                                                                     ▼
                                                     Serverless transform:
                                                       read manifest + trmnl.state,
                                                       pick next patent,
                                                       save state, return 1 patent
                                                                     │
                                                                     ▼
                                                     Liquid markup per layout:
                                                       <img> drawing + HTML caption
                                                                     │
                                                                     ▼
                                                     TRMNL renders and dithers once
```

- **No server of our own.** GitHub Pages hosts static files, and TRMNL's
  Serverless transform does the picking. Delete or keep the Image Display
  setup; the two can run side by side during the switch.
- **The data changes every refresh** because the transform returns a different
  patent each poll, so TRMNL re-renders.
- **State is per plugin instance** (`trmnl.state`). Each device, and each
  mashup slot if it's its own instance, keeps its own no-repeat queue.

### 3.1 Build pipeline additions (this repo)

Add `src/plugin.py` and a `make plugin` target (also run by `make build`). It
writes `output/plugin/`:

- **`drawings/<slug>.png`**: the drawing **only**, with no caption. Use the
  existing `clean_drawing()` (rotation, crop, erase, paper flatten, ink trim),
  scaled so the long side is 1600 px. Apply line thickening for a ~400 px
  display size (`fit_drawing(..., supersample=…)`), darken midtones
  (`gamma 1.7`, as in `src/trmnl.py`), and save as 8-bit grayscale PNG.
  Pad nothing: the markup does layout.
- **`manifest.json`**, kept under ~100 KB:
  ```json
  {
    "version": 1,
    "generated": "2026-11-25T00:00:00Z",
    "base_url": "https://johnlago.github.io/patent-wallpapers/plugin/",
    "patents": [
      {
        "slug": "us5443036-method-of-exercising-a-cat",
        "number": "5,443,036",
        "year": "1995",
        "title": "Method of exercising a cat",
        "inventors": ["Kevin T. Amiss", "Martin H. Abbott"],
        "image": "drawings/us5443036-method-of-exercising-a-cat.png",
        "aspect": 1.92,
        "added": "2026-11-24T21:46:00Z"
      }
    ]
  }
  ```
  - **Fields**: title, inventor and year use the same overrides and
    `tidy_name` / `nice_title` / `pretty_number` logic as `caption_text()` in
    `src/build.py`. Reuse it; don't copy it.
  - `aspect` is width ÷ height of the drawing PNG.
  - `added` is the date of the first git commit containing the patent's
    `patents.toml` entry or drawing. Reuse the git-history approach in
    `src/rotate.py`, `added_times()`. Patents in the original set get their
    real first-commit date.
- Have the existing Pages workflow also copy `output/plugin/` into the site, at
  `site/plugin/`. It doesn't need to run on a schedule for the plugin; push
  triggers are enough. Keep the 6-hour schedule only while Image Display is in
  use.

### 3.2 Serverless transform (Python preferred)

Its input is the polled `manifest.json`. Exactly how the polled body appears
in `input` is **VERIFY**; trmnlp passes it on stdin as JSON. Its output is the
merge variables for one patent:

```json
{
  "slug": "...", "number": "5,443,036", "year": "1995",
  "title": "Method of exercising a cat",
  "inventors": "Kevin T. Amiss, Martin H. Abbott",
  "image_url": "https://johnlago.github.io/patent-wallpapers/plugin/drawings/....png",
  "aspect": 1.92,
  "is_new": false,
  "pick_id": 1234
}
```

`pick_id` is a counter that always increases. It guarantees the merge
variables differ even if a 1-patent set picks the same slug twice.

**Selection algorithm** (state kept in `trmnl.state`):

```
state = { queue: [slug...], seen_added_max: ISO date, pick_id: int }

1. patents = manifest.patents; drop slugs no longer present from state.queue.
2. new = patents with added > state.seen_added_max, oldest first.
   If any: pick = new[0]; seen_added_max = pick.added; is_new = true.
   This is "new patents go first". Bootstrap: on first run with no state,
   set seen_added_max = now, so the whole back catalog isn't "new".
3. Else: if queue is empty, refill it with a shuffled list of all slugs,
   making sure its first item isn't the last patent shown (no repeats across
   the reshuffle boundary). pick = queue.pop(0).
4. A new patent picked in step 2 is also removed from the current queue, so
   it isn't shown again before the next reshuffle.
5. pick_id += 1; save state; return the merge variables.
```

- **Per-instance queue**: this gives real no-repeats with no cycle-boundary
  repeats. Adding patents doesn't reshuffle; new ones jump in once, then join
  the next refill.
- **Fallback if Saved State turns out unavailable or unreliable**: pick
  statelessly with the `src/rotate.py` approach, using slot =
  `timestamp // refresh_seconds`, a seeded shuffle, and new-first by `added`.
  Compute `refresh_seconds` from a custom field, default 900.
- **Form field `rotation`** (select: `Shuffle (no repeats)` | `Random` |
  `Newest first`), default Shuffle. Optional; keep v1 small.

### 3.3 Markup (Liquid)

- **Shared tab**: CSS and a `{% template caption %}` partial with the patent
  number · year line, title and inventors. One partial is used by all layouts.
- **Layout tabs**: each decides **stack** (caption under drawing) or **side**
  (caption column to the left of the drawing) from `aspect` against the slot's
  aspect, following the current design rules:
  - **full**: side if `aspect` < ~1.25, else stack. Tune against the
    `output/trmnl/contact-full.png` look.
  - **half_vertical**: always stack, with the caption pinned to the bottom
    margin like the e-reader layout.
  - **half_horizontal**: always side, caption left.
  - **quadrant**: side or stack by aspect. Must include inventors. The patent
    number line must stay on one line; shrink the drawing, not the text.
- **Design rules to carry over** (all decided in earlier review):
  - No divider rule, except in half_vertical, which mirrors the e-reader
    layout.
  - The number · year line never wraps. Titles take at most 2 lines (3 in
    quadrant), with balanced breaks and no dangling function words; see
    `set_title()`.
  - Generous vertical spacing around the title in side-by-side captions. Even
    spacing between the outer margins and the drawing/caption gap.
  - In side layouts the caption is left and the drawing right.
- **Text balance**: use CSS `text-wrap: balance` for titles if the renderer
  supports it (**VERIFY**). Otherwise the transform can return pre-broken
  title lines as `title_lines` by porting `set_title()`, which is the safer
  choice.
- **Drawing**: `<img>` with `object-fit: contain` in a flex box. Check the
  framework's image classes (`/framework/docs/3.4/image`, `rendering_modes`)
  for how images are dithered at 2-bit, and use the framework's recommended
  classes.
- **Typeface**: the current images use Bookerly, which is proprietary and
  can't be hosted or shipped in a public recipe. Pick an open serif with a
  true italic that suits book-style captions. **Literata** (OFL) is the
  closest in spirit. Load it with the framework's "Custom Typefaces" mechanism
  (**VERIFY**), or else a `<link>` to a hosted woff2 on GitHub Pages. Fall
  back to the framework serif if custom fonts aren't allowed.
- **Device independence**: size everything in proportion to the slot, using
  framework layout classes and `trmnl.device.*`. Never hard-code 800×480.

## 4. Repo layout

```
src/plugin.py                  # builds output/plugin/ (drawings + manifest)
trmnl-plugin/                  # trmnlp project, pushed with `trmnlp push`
  .trmnlp.yml                  # local only: asset_overrides -> output/plugin/drawings
  src/settings.yml             # polling URL = …/plugin/manifest.json, refresh 15 min, fields
  src/shared.liquid
  src/full.liquid
  src/half_horizontal.liquid
  src/half_vertical.liquid
  src/quadrant.liquid
  src/transform.py             # Serverless run(input), if trmnlp supports a file for it
  test/                        # trmnlp tests with a fixed clock and sample state
```

Keep `src/trmnl.py`, `src/rotate.py` and the Image Display images until the
plugin has run well on the device for a few days. Then retire them in a
separate change.

## 5. Acceptance criteria

1. Every plugin refresh shows a different patent. Within one instance, no
   patent repeats until all have been shown, including across reshuffles.
2. Pushing a commit that adds a patent shows it on the next refresh of every
   instance, once, before the normal queue resumes.
3. All four layouts look right in `trmnlp serve` / `trmnlp build --png` for
   every patent: no clipped text, no wrapped number line, title ≤ 2 lines
   (≤ 3 in quadrant), inventors present. Produce a contact sheet per layout
   from the trmnlp PNGs, like the current `output/trmnl/contact-*.png`, for
   review.
4. On the user's original TRMNL (4-gray mode), a full screen and a mashup with
   all three slot shapes look as good as or better than the Image Display
   version. The user confirms this; it can't be checked automatically.
5. Renders finish well inside 5 s: drawings ≤ ~200 KB each, served from
   GitHub Pages.
6. Transform output is ≤ 5 KB and runs in < 1 s.
7. `trmnlp lint` passes. The plugin is pushed with `trmnlp push`, with `id`
   set in `settings.yml` so pushes update rather than duplicate.
8. The README documents adding a patent (unchanged: `patents.toml` → `make` →
   review → push) and installing/configuring the plugin.

## 6. Out of scope for v1

- Publishing as a public Recipe. Design for it (no secrets, sensible field
  defaults, open font) but don't submit until the user asks.
- Automated discovery of new patents ("patent of the day" without a human
  review step).
- TRMNL X–specific art direction beyond proportional scaling.

## 7. Risks and decisions for the builder

| Risk | Mitigation |
|---|---|
| Saved State API differs or isn't on the user's plan | Stateless fallback (§3.2). |
| Polled manifest too large for transform input | Keep the manifest lean, or split it into `manifest.json` (slugs + added) and per-patent JSON the transform fetches; transforms have network access. |
| 2-bit dithering of `<img>` looks worse than today | Try framework image classes and rendering modes. Compare `gamma` 1.4–2.0 on the device. |
| Custom fonts not supported | Framework serif; keep captions short. |
| Each mashup slot needs its own plugin instance | Each instance has its own state, which is fine. Document adding one instance per slot. |
| `text-wrap: balance` unsupported | Return `title_lines` from the transform. |

## 8. First step: a verification spike (done; see §9)

Spend the first part of the session confirming the **VERIFY** items, with a
throwaway private plugin on the user's account. Ask the user before pushing
anything to their TRMNL account.

1. Read help article 16777795 ("Saved State"): the exact `trmnl.state`
   read/write API, persistence, and whether it's per instance.
2. Confirm the transform runs on every poll, and see how the polled JSON
   arrives in `input`.
3. Read framework 3.4 `image`, `image_stroke`, `rendering_modes` and
   `custom_typefaces`, and render one drawing at 2-bit.
4. Check whether the polling response has a size limit.
5. Confirm a changing `pick_id` alone triggers a re-render.

Report findings to the user, adjust this spec if needed, then build.

## 9. Spike findings and build decisions (2026-11-24)

Sources: help.trmnl.com articles 16777795 (Saved State), 14130649 (Serverless)
and 9510536 (Private Plugins); trmnl.com/framework/docs/3.4 (image,
image_stroke, rendering_modes, custom_typefaces, devices, view, mashup, clamp);
and the trmnlp 0.34.1 source in the `trmnl/trmnlp` Docker image, which mirrors
TRMNL's server behaviour.

| Item | Finding | Effect on the build |
|---|---|---|
| Saved State | Read `input.trmnl.state` (`{}` on first run). Write by returning a `trmnl_state` key, which is removed from the merge variables. It must be an object of at most 8192 bytes; anything else is ignored and the old state kept. State belongs to the install. Force Refresh keeps it. A failed poll doesn't save it. | The stateful algorithm in §3.2 is used, so the stateless fallback isn't needed. The queue stores short ids (`us5443036`), so 50 patents take about 0.5 KB. If the state ever nears the limit, the transform truncates the queue. |
| Polled JSON in `input` | With one polling URL, the JSON is merged at the top level of `input` next to `trmnl`; with several, it sits under `IDX_0`, `IDX_1`, … `run(input)` must return an object. TRMNL wraps the file in its own runner, so `from __future__` fails. Polling has no documented size limit; the 5/10 KB limits are for webhooks. | The transform accepts either shape. If the poll brought nothing, it fetches the manifest itself. The manifest is 45 KB. |
| Re-render | "By default, our backend skips generating screens if the merge variables are the same between requests." | `pick_id` goes up on every run, so the variables always change. The transform is tested for this; the real device still has to confirm it (criterion 4). |
| Dithering | `image-dither` is a page-level switch. TRMNL's converter (copied by trmnlp's `ImageQuantizer`) Floyd–Steinberg dithers the **whole screenshot**, text included, when the markup contains that string. Without it, the screenshot is posterized to the panel's grays with no dither. On the 4-gray OG that is 0/85/170/255, the same as the e-reader 2bpp set. | No `image-dither`. Drawings keep the gamma-1.7 midtone darkening and land on solid grays, and text stays crisp. Note that the literal string `image-dither` anywhere in the markup turns dithering on. |
| Custom typefaces | `@font-face` with a remote `url()` in a `<style>`, plus the `typeface` class and `--framework-typeface`. Weights 200–700 are requested by framework text classes. | The markup sets `font-family` directly, because it uses no framework text classes. |
| Typeface | Bookerly can't ship. At the user's request, **Libron** (OFL, github.com/nicoverbruggen/libron, a Readerly/Newsreader derivative tuned for e-readers) replaces Literata. "Libron" is a Reserved Font Name, so subsetting or converting it would require renaming it. | `fonts/libron/` holds the v0.32 release files unmodified: TTFs for caption measurement and the official Web WOFF2s (about 85 KB each) for the plugin, with LICENSE and COPYRIGHT. |
| `text-wrap: balance` | Not mentioned in the framework docs. | Titles aren't wrapped by the browser. Their breaks come from `set_title()` at build time. |
| Slot sizes | The framework docs give no pixel sizes. trmnlp's 800×480 mashup render gives quadrant 385×225, which matches `patents.toml`. | The markup scales one reference canvas per layout to whatever the slot is, using container query units. |

### What changed from §3

- **Layout is decided at build time, not in Liquid.** `src/plugin.py` runs
  the same arrangement rules as the Image Display set: `src/trmnl.py`'s `compose`
  was split into `plan()` + drawing, with byte-identical output. It measures with
  Libron's metrics and stores a per-layout plan in each manifest entry:
  arrangement, drawing box, caption box, header lines, title lines and title
  size. The Liquid only places those boxes, in units of one reference pixel
  (`--u`), and sets real text. So "side if aspect < ~1.25" is replaced by the
  exact "whichever shows the drawing larger" rule already reviewed.
- **Plugin-only tweaks** go in `[plugin.<layout>]` tables in `patents.toml`, which
  override `[trmnl.<layout>]` for the plugin alone. After review: more room
  around the title in half_vertical (`line_gap` 20) and in stacked quadrant
  captions (14). The drawings shrink to make room.
- **Spacing is by cap height and baseline**, as in `caption_block()`. The
  `@font-face` rules pin Libron's ascent/descent (80%/20%), so the CSS margins
  reproduce each `line_gap`.
- **Drawings are 16-gray 4-bit PNGs**, long side 1600 px. 8-bit files were up to
  370 KB; at 16 grays the largest is 172 KB and the set is 4.3 MB.
- **`added`** comes from git at deploy time. `src/plugin.py stamp` runs in the
  Pages workflow and reuses `rotate.added_times()`.
- **No custom fields** except `author_bio`, which lint requires for recipes. The
  `rotation` select was left out of v1.
- **trmnlp runs in Docker** (`make plugin-lint`, `plugin-test`,
  `plugin-contact`, `plugin-serve`). The project mounts the repo root, so tests
  and previews read `output/plugin/` through `asset_overrides`.

### Still to confirm on the device (needs a push to the TRMNL account)

1. A changing `pick_id` triggers a new screen on every refresh.
2. The 4-gray OG render of a full screen and a mashup looks as good as Image
   Display (criterion 4).
3. Whether a plugin instance used in several mashups shares one saved state.
