# Patent Wallpapers

Odd, funny, and quirky U.S. patent drawings, formatted as sleep screens for the
**Eegoread A4** e-reader running CrossPoint.

![contact sheet](output/contact-sheet.png)

## Target format

| | |
|---|---|
| Screen | 3.98" E Ink, UC8279C controller |
| Resolution | **552 × 768** portrait (panel is 768 × 552 native, 238 PPI) |
| Gray levels | 4 (2 bits per pixel), so images are pre-quantized to 0 / 85 / 170 / 255 |
| File | **2-bit BMP**, 4-entry palette, exactly 552 × 768 |

CrossPoint shows a sleep image directly only when it is exactly screen-sized
and 2 bits per pixel or less. Anything else goes through its converter
(`BmpToBmpConverter`), which Atkinson-dithers with X4-tuned thresholds: below 45
is black, below 70 dark gray, below 140 light gray, and the rest white. That
lightens mid-grays, so anti-aliased text turns wispy. This applies even to
8-bit files whose pixels already sit on the 4 levels.

The build therefore writes two sets:

- `output/2bpp/`: recommended. True 2-bit files the device shows
  pixel-for-pixel.
- `output/gray/`: 8-bit full grayscale with no pre-quantization, for when you'd
  rather let CrossPoint do the conversion.

## Install on the device

1. Copy the BMPs to a `.sleep` folder at the root of the SD card. A folder named
   `sleep` also works.
   ```bash
   mkdir -p /Volumes/SDCARD/.sleep && cp output/2bpp/*.bmp /Volumes/SDCARD/.sleep/
   ```
2. On the device, set **Settings → Sleep Screen** to **Custom**.

CrossPoint picks a random image each time the device sleeps. The first sleep
with a new image is slower because the device converts it once.

## Pipeline

```bash
pip install -r requirements.txt   # just Pillow
make            # fetch + build
make fetch      # download metadata + drawing sheets into cache/
make build      # render output/{2bpp,gray,preview}/ and output/contact-sheet.png
```

- `src/fetch.py` pulls each patent's Google Patents page through `curl`, because
  Google answers Python's urllib with 503s. It records the title, dates, and
  inventors, and saves every full-resolution drawing sheet to
  `cache/<number>/sheet-NN.png`. Run `python src/fetch.py US1234567` to preview
  any patent's title and sheet count before adding it.
- `src/build.py` processes each entry in `patents.toml`:
  1. Optional manual crop and rotation.
  2. Paper cleanup: autocontrast, then pixels lighter than the `paper` threshold
     become white.
  3. A median filter (`despeckle`) removes scan specks.
  4. Header stripping detects and removes the lone printed "U.S. Patent … Sheet N
     of M" line on modern sheets.
  5. An auto-trim crops to the ink.
  6. Lines are thickened before the ~4–5× downscale, so hairlines survive.
  7. The drawing is fitted into the frame above a caption with the patent
     number, year, title, and inventor.
  8. The 2bpp set is snapped to the device's 4 gray levels. The gray set is left
     as is.

  Captions are set in Bookerly from `~/Library/Fonts`, falling back to Georgia.
  To use another font, drop `regular.ttf` and `italic.ttf` into a `fonts/` folder.
  Caption sizes and spacing are under `[style]` in `patents.toml`. Lines are placed
  by measured cap height and baseline, so the gaps there are the gaps you see.

### Adding a wallpaper

1. Find a patent on [Google Patents](https://patents.google.com). Patents from
   before about 1920 need the kind code, for example `US730918A`.
2. Run `python src/fetch.py <number>` to check the title and how many sheets it
   has.
3. Add a `[[wallpaper]]` block to `patents.toml`. The available keys are
   documented at the top of that file.
4. Run `make build` and look at `output/contact-sheet.png`.

To target a different device, change `[device]`.

## The set

| Patent | Year | Title |
|---|---|---|
| US 6,293,874 | 2001 | User-operated amusement apparatus for kicking the user's buttocks |
| US 556,248 | 1896 | Saluting device (tips your hat for you) |
| US 730,918 | 1903 | Eye-protector for chickens |
| US 4,022,227 | 1977 | Method of concealing partial baldness (the patented comb-over) |
| US 256,265 | 1882 | Device for waking persons from sleep (drops corks on your face) |
| US 5,443,036 | 1995 | Method of exercising a cat (laser pointer) |
| US 3,216,423 | 1965 | Apparatus for facilitating the birth of a child by centrifugal force |
| US 5,971,829 | 1999 | Motorized ice cream cone |
| US 11,942 | 1854 | Tapeworm-trap |
| US 4,233,942 | 1980 | Animal ear protectors |
| US 5,457,821 | 1995 | Hat simulating a fried egg |
| US 4,344,424 | 1982 | Anti-eating face mask |
| US 81,437 | 1868 | Improved burial-case (coffin with an escape bell) |
| US 4,984,302 | 1991 | Nose-worn air filter |
| US 6,004,596 | 1999 | Sealed crustless sandwich |

U.S. patent drawings are public domain. Drawing sheets come from Google Patents.
