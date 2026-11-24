"""Fallback source: the USPTO's full-document PDFs.

Google Patents rate-limits heavy use. The USPTO serves every granted patent
(1790 onward) as a PDF of scanned pages, one fax-compressed (CCITT) image per
page. This module pulls those page images out with Pillow alone, and on macOS
reads the title, inventor, and date off the scans with the Vision framework.
"""
from __future__ import annotations

import io
import re
import shutil
import struct
import subprocess
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
PDF_URL = "https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/{}"
OCR_SRC = ROOT / "src" / "ocr.swift"
OCR_BIN = ROOT / "cache" / ".ocr"

MONTHS = "Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec"


def doc_id(number: str) -> str:
    """US730918A -> 0730918, US10952487B2 -> 10952487, USD539422S1 -> D0539422."""
    m = re.fullmatch(r"US(D|RE|PP)?(\d+)([A-Z]\d?)?", number.upper())
    if not m:
        raise ValueError(f"can't parse patent number {number!r}")
    prefix, digits = m.group(1) or "", m.group(2)
    return prefix + digits.zfill(7 - len(prefix) if prefix else 7)


# --- PDF page images ---------------------------------------------------------

def _int(d: bytes, key: bytes, objs: dict[int, bytes]) -> int | None:
    m = re.search(rb"/" + key + rb"\s+(\d+)(\s+0\s+R)?", d)
    if not m:
        return None
    if m.group(2):  # indirect reference
        o = objs.get(int(m.group(1)))
        return int(o.split()[0]) if o else None
    return int(m.group(1))


def _tiff(data: bytes, w: int, h: int, k: int) -> bytes:
    """Wrap a raw CCITT stream in a minimal single-strip TIFF Pillow can decode."""
    comp = 4 if k < 0 else 3
    tags = [(256, 4, w), (257, 4, h), (258, 3, 1), (259, 3, comp), (262, 3, 0),
            (273, 4, 8), (277, 3, 1), (278, 4, h), (279, 4, len(data))]
    if comp == 3:
        tags.append((292, 4, 1 if k > 0 else 0))
    ifd = struct.pack("<H", len(tags))
    for tag, typ, val in sorted(tags):
        packed = struct.pack("<HH", val, 0) if typ == 3 else struct.pack("<I", val)
        ifd += struct.pack("<HHI", tag, typ, 1) + packed
    return b"II*\x00" + struct.pack("<I", 8 + len(data)) + data + ifd + b"\0\0\0\0"


def pdf_pages(pdf: bytes) -> list[Image.Image]:
    objs = {int(m.group(1)): m.group(2)
            for m in re.finditer(rb"(\d+)\s+0\s+obj(.*?)endobj", pdf, re.S)}
    pages = []
    for _, body in sorted(objs.items()):
        if not re.search(rb"/Subtype\s*/Image", body):
            continue
        d, _, rest = body.partition(b"stream")
        rest = rest[2:] if rest.startswith(b"\r\n") else rest[1:]
        data = rest[: _int(d, b"Length", objs)]
        w, h = _int(d, b"Width", objs), _int(d, b"Height", objs)
        if b"CCITTFaxDecode" in d:
            k = re.search(rb"/K\s+(-?\d+)", d)
            im = Image.open(io.BytesIO(_tiff(data, w, h, int(k.group(1)) if k else 0))).convert("L")
            if b"/BlackIs1 true" in d:
                im = Image.eval(im, lambda v: 255 - v)
        elif b"DCTDecode" in d:
            im = Image.open(io.BytesIO(data)).convert("L")
        else:
            continue
        pages.append(im)
    return pages


# --- OCR + metadata ----------------------------------------------------------

def ocr(paths: list[Path]) -> list[str]:
    """Text of each image, top to bottom. Empty strings where OCR isn't available."""
    if not OCR_BIN.exists():
        if not shutil.which("swiftc"):
            return [""] * len(paths)
        OCR_BIN.parent.mkdir(parents=True, exist_ok=True)
        r = subprocess.run(["swiftc", "-O", str(OCR_SRC), "-o", str(OCR_BIN)], capture_output=True)
        if r.returncode:
            return [""] * len(paths)
    r = subprocess.run([str(OCR_BIN), *map(str, paths)], capture_output=True, text=True)
    chunks = re.split(r"^== .*$\n?", r.stdout, flags=re.M)[1:]
    return chunks + [""] * (len(paths) - len(chunks))


def lines(chunk: str, column: str = "all") -> str:
    """Plain text from OCR output lines "x0 y0 x1 y1<TAB>text" (top-left origin, 0..1).
    column="left" keeps the left column of a two-column front page."""
    rows = []
    for l in chunk.splitlines():
        box, _, text = l.partition("\t")
        try:
            x0, y0, x1, y1 = map(float, box.split())
        except ValueError:
            continue
        if column == "left" and x1 > 0.56:
            continue
        rows.append((y0, x0, text))
    return "\n".join(t for _, _, t in sorted(rows))


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip(" .,")


def parse_old(text: str) -> dict:
    """Pre-1920s specification page:
        UNITED STATES PATENT OFFICE.
        MARTIN GOETZE, OF BERLIN, GERMANY.
        DEVICE FOR PRODUCING DIMPLES.
        SPECIFICATION forming part of Letters Patent No. 560,351, dated May 19, 1896.
    """
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    out: dict = {}
    for i, l in enumerate(lines):
        if re.search(r"PATENT\s+OFFICE", l, re.I):
            names = lines[i + 1] if i + 1 < len(lines) else ""
            out["inventors"] = [n.title() for n in re.findall(r"([A-Z][A-Z. ]+?), OF ", names.upper())]
            if i + 2 < len(lines):
                out["title"] = _clean(lines[i + 2]).capitalize()
            break
    m = re.search(rf"dated\s+((?:{MONTHS})\w*\.?\s+\d+,\s+(\d{{4}}))", text)
    if m:
        out["publication_date"] = m.group(2)
    return out


def parse_modern(text: str) -> dict:
    """1970s+ front page with INID codes: [54] or (54) title, [75]/(72)/(76) inventors, Date of Patent."""
    out: dict = {}
    t = re.search(r"[\[(]54[\])]\s*(.+?)\s*[\[(]7[0-9][\])]", text, re.S)
    if t:
        title = re.split(r"[\[(]\d\d[\])]", t.group(1))[0]
        out["title"] = _clean(title).capitalize()
    inv = re.search(r"[\[(]7[256][\])]\s*Inventors?:\s*(.+?)\s*(?:[\[(]\d\d[\])]|\(\*\)|Notice:)", text, re.S)
    if inv:
        # "Michael J. Jackson, Los Angeles; Michael L. Bush; Dennis Tompkins, both of ..."
        names = [_clean(re.sub(r",.*", "", n, flags=re.S)) for n in re.split(r";|\band\b", inv.group(1))]
        out["inventors"] = [n for n in names if len(n.split()) >= 2 and not n.lower().startswith("both")][:4]
    d = re.search(rf"(?:Date of Patent|Patent Date)\D*?((?:{MONTHS})\w*\.?\s*\d+,\s*(\d{{4}}))", text)
    if d:
        out["publication_date"] = d.group(2)
    return out


def fetch(number: str, out: Path, get) -> dict:
    """Save every page as sheet-NN.png and return whatever metadata OCR can find."""
    pages = pdf_pages(get(PDF_URL.format(doc_id(number))))
    if not pages:
        raise RuntimeError("USPTO PDF had no page images")
    out.mkdir(parents=True, exist_ok=True)
    names = []
    for i, im in enumerate(pages):
        name = f"sheet-{i:02d}.png"
        im.save(out / name, optimize=True)
        names.append(name)

    return {**read_meta(out, names), "sheets": names}


def read_meta(out: Path, names: list[str]) -> dict:
    meta = {"title": "", "inventors": [], "publication_date": None, "priority_date": None}
    raw = ocr([out / n for n in names[:6]])  # front page / first spec page is early
    (out / "ocr.txt").write_text("\n\n=====\n\n".join(lines(c) for c in raw))
    for chunk in raw:
        text = lines(chunk)
        if re.search(r"[\[(]54[\])]", text):
            found = parse_modern(lines(chunk, "left"))
            found["publication_date"] = parse_modern(text).get("publication_date")
        else:
            found = parse_old(text)
        for k, v in found.items():
            if v and not meta.get(k):
                meta[k] = v
        if meta["title"] and meta["inventors"] and meta["publication_date"]:
            break
    if not meta["publication_date"]:
        # "Patented May 19, 1896" on old drawing sheets, or the
        # "U.S. Patent  Oct. 26, 1993  Sheet 1 of 4" header on modern ones.
        date = rf"(?:{MONTHS})\w*\.?\s*\d+,?\s*(\d{{4}})"
        for text in map(lines, raw):
            m = (re.search(r"Patented\s+" + date, text)
                 or re.search(date + r"[\s\S]{0,40}?Sheet\s+\d", text))
            if m:
                meta["publication_date"] = m.group(1)
                break
    if not meta["publication_date"] and raw:
        # Last resort: the patent date sits at the top of a modern front page.
        m = re.search(date, lines(raw[0]))
        meta["publication_date"] = m.group(1) if m else None
    return meta
