#!/usr/bin/env python3
"""Turn a PDF into Markdown, keeping italics, footnotes and the reading order.

Two kinds of page, often in one file:

  typeset pages (e-books, born-digital articles): the text layer names the font of
      every glyph, so italic and bold come straight from the typesetting;
  scanned pages (JSTOR, library scans, earlier OCR runs): the page is an image.
      These are read with Tesseract, cross-checked against any OCR layer the PDF
      already has, and the image itself supplies what OCR doesn't: italics (from
      the slant of the strokes), footnote figures and subscripts (from their size
      and height). Needs the tesseract and poppler programs; slower (a few seconds
      per page).

Output:
  - italic / bold          -> *italic*, **bold**, ***both***
  - larger type            -> # headings; centered section numerals (I, II, ...) too
  - two-column pages       -> read column by column, full-width parts in place
  - footnote markers       -> [^1] with the note text as [^1]: ... at the end
  - running heads, folios  -> dropped (page numbers optionally kept, --page-markers)
  - JSTOR cover page       -> YAML front matter (title, author, source, URL)
  - indented block quotes  -> > quote; numbered premises -> 1. lists
  - line-end hyphenation   -> joined ('specu-' + 'lative' -> 'speculative'),
                              keeping real compounds ('self-consciousness')

Do not run run_tesseract.py on a typeset PDF first: it rebuilds the pages from images
and throws the real text layer — and with it the italics — away.

Usage:
    python pdf_to_markdown.py book.pdf                  # writes book.md
    python pdf_to_markdown.py book.pdf -o ote.md --pages 12-18
    python pdf_to_markdown.py book.pdf --page-markers   # adds {p. 25} at page breaks
    python pdf_to_markdown.py scan.pdf --no-ocr         # scans: use only the PDF's own layer
"""

from __future__ import annotations

import argparse
import re
import shutil
import statistics
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

try:
    from pdfminer.converter import PDFPageAggregator
    from pdfminer.layout import (
        LAParams,
        LTAnno,
        LTChar,
        LTCurve,
        LTImage,
        LTTextLineHorizontal,
    )
    from pdfminer.pdfinterp import PDFPageInterpreter, PDFResourceManager
    from pdfminer.pdfpage import PDFPage
except ImportError:  # pragma: no cover
    print("ERROR: pdfminer.six is not installed: pip install -r requirements.txt", file=sys.stderr)
    sys.exit(1)


# --------------------------------------------------------------------------------------
# Font style
# --------------------------------------------------------------------------------------

_ITALIC_FLAG = 1 << 6  # PDF font descriptor flag bit 7
_FORCE_BOLD_FLAG = 1 << 18  # bit 19
# TeX-style names carry the style in a prefix: cmti10 (text italic), cmbxti10, cmsl10 ...
_TEX_ITALIC = re.compile(r"^(cmti|cmbxti|cmsl|cmbxsl|cmitt|lmromanslant)", re.I)
_TEX_BOLD = re.compile(r"^(cmbx|cmb\d)", re.I)


def _style_part(fontname: str) -> tuple[str, str]:
    """Split 'ABCDEF+MinionPro-BoldIt' into ('minionpro', 'boldit')."""
    name = fontname.split("+", 1)[-1]
    for sep in ("-", ","):
        if sep in name:
            base, style = name.rsplit(sep, 1)
            return base.lower(), style.lower()
    return name.lower(), ""


def font_style(font, matrix) -> tuple[bool, bool]:
    """(italic, bold) for a pdfminer font, from its name, descriptor and text matrix."""
    name = str(getattr(font, "fontname", "") or "")
    base, style = _style_part(name)
    full = name.lower()
    flags = int(getattr(font, "flags", 0) or 0)
    angle = float(getattr(font, "italic_angle", 0) or 0)

    italic = (
        any(k in full for k in ("italic", "oblique", "slanted", "kursiv"))
        or style.endswith("it")
        or bool(_TEX_ITALIC.match(base or full))
        or bool(flags & _ITALIC_FLAG)
        or abs(angle) >= 4
    )
    # Synthetic oblique: upright font sheared by the text matrix.
    a, b, c, d = matrix[:4]
    if not italic and b == 0 and d and abs(c / d) > 0.12:
        italic = True

    weight = 0
    try:
        weight = int(font.descriptor.get("FontWeight", 0) or 0)
    except Exception:
        pass
    bold = (
        any(k in style or k in full for k in ("bold", "black", "heavy", "semibold", "demi"))
        or bool(_TEX_BOLD.match(base or full))
        or bool(flags & _FORCE_BOLD_FLAG)
        or weight >= 600
    )
    return italic, bold


class _StyledAggregator(PDFPageAggregator):
    """PDFPageAggregator that remembers each glyph's italic/bold style.

    pdfminer's LTChar keeps only the font *name*; the descriptor (italic flag, italic
    angle, weight) is gone by the time the layout comes back, so tag it here.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.glyphs = 0
        self.invisible_glyphs = 0  # text render mode 3: the hidden layer of an OCR'd scan
        self._invisible = False

    def render_string(self, textstate, *args, **kwargs):
        self._invisible = textstate.render == 3
        return super().render_string(textstate, *args, **kwargs)

    def render_char(self, matrix, font, *args, **kwargs):
        adv = super().render_char(matrix, font, *args, **kwargs)
        item = self.cur_item._objs[-1]
        item.italic, item.bold = font_style(font, matrix)
        self.glyphs += 1
        self.invisible_glyphs += self._invisible
        return adv


# --------------------------------------------------------------------------------------
# Rows: visual lines of glyphs
# --------------------------------------------------------------------------------------

_LIGATURES = {"ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl", "ﬅ": "st", "ﬆ": "st"}
_MARKER_LABEL = re.compile(r"^(?:\d{1,3}|[*∗†‡§¶]{1,3}|[a-z]|\?)$")


@dataclass
class Glyph:
    text: str
    italic: bool = False
    bold: bool = False
    size: float = 0.0
    x0: float = 0.0
    x1: float = 0.0
    y0: float = 0.0
    sup: bool = False
    marker: str | None = None  # footnote reference label (pseudo-glyph)
    note: int | None = None  # footnote id, on the first glyph of a reference
    ocr: bool = False  # read from a scan: the style of punctuation is a guess

    @property
    def is_space(self) -> bool:
        return self.marker is None and self.text.isspace()


@dataclass
class Row:
    glyphs: list[Glyph]
    x0: float
    x1: float
    top: float
    bottom: float
    page: int
    size: float = 0.0
    baseline: float = 0.0
    frame: tuple[float, float] | None = None  # the column (or full width) it sits in
    fuzzy: bool = False  # size estimated from a scan, not read from the font

    @property
    def text(self) -> str:
        return "".join(g.text if g.marker is None else "" for g in self.glyphs).strip()

    @property
    def plain_text(self) -> str:
        """Text without superscript markers — for heading/footnote label checks."""
        return "".join(g.text for g in self.glyphs if g.marker is None and not g.sup).strip()


@dataclass
class Page:
    number: int  # 1-based PDF page
    width: float
    height: float = 0.0
    rows: list[Row] = field(default_factory=list)
    rules: list[tuple[float, float, float]] = field(default_factory=list)  # (x0, x1, y)
    folio: str | None = None  # printed page number, if found
    scanned: bool = False


def _line_glyphs(line) -> list[Glyph]:
    out: list[Glyph] = []
    for obj in line:
        if isinstance(obj, LTChar):
            if not obj.upright:
                continue  # rotated text: margin stamps, watermarks
            text = _LIGATURES.get(obj.get_text(), obj.get_text())
            out.append(
                Glyph(
                    text=text,
                    italic=getattr(obj, "italic", False),
                    bold=getattr(obj, "bold", False),
                    size=obj.size,
                    x0=obj.x0,
                    x1=obj.x1,
                    y0=obj.y0,
                )
            )
        elif isinstance(obj, LTAnno) and obj.get_text() == " " and out:
            out.append(Glyph(" ", size=0.0, x0=out[-1].x1, x1=out[-1].x1, y0=out[-1].y0))
    return out


def _walk(obj, lines, rules, images):
    if isinstance(obj, LTTextLineHorizontal):
        lines.append(obj)
        return
    if isinstance(obj, LTImage):
        images.append(obj.bbox)
        return
    if isinstance(obj, LTCurve):  # LTLine and LTRect are LTCurves
        if obj.height <= 2 and obj.width >= 20:
            rules.append((obj.x0, obj.x1, (obj.y0 + obj.y1) / 2))
        return
    try:
        children = list(obj)
    except TypeError:
        return
    for child in children:
        _walk(child, lines, rules, images)


def _build_rows(lines, page_no: int) -> list[Row]:
    """Merge pdfminer lines that share a baseline band into visual rows.

    A running head's folio and title, or a superscript that pdfminer split off, are
    separate 'lines' to pdfminer but one row on the page.
    """
    items = []
    for ln in lines:
        glyphs = _line_glyphs(ln)
        if any(not g.is_space for g in glyphs):
            items.append((ln.y1, ln.y0, ln.x0, glyphs))
    items.sort(key=lambda t: (-t[0], t[2]))

    groups: list[list] = []
    for top, bottom, x0, glyphs in items:
        for grp in groups:
            g_top = max(t for t, _, _, _ in grp)
            g_bot = min(b for _, b, _, _ in grp)
            overlap = min(top, g_top) - max(bottom, g_bot)
            if overlap > 0.5 * min(top - bottom, g_top - g_bot):
                grp.append((top, bottom, x0, glyphs))
                break
        else:
            groups.append([(top, bottom, x0, glyphs)])

    rows: list[Row] = []
    for grp in groups:
        grp.sort(key=lambda t: t[2])
        glyphs: list[Glyph] = []
        for _, _, _, gl in grp:
            if glyphs and gl:
                gap = gl[0].x0 - glyphs[-1].x1
                ref = max(g.size for g in gl + glyphs[-3:])
                if gap > 0.15 * ref and not glyphs[-1].is_space and not gl[0].is_space:
                    glyphs.append(Glyph(" ", x0=glyphs[-1].x1, x1=gl[0].x0, y0=gl[0].y0))
            glyphs.extend(gl)
        while glyphs and glyphs[-1].is_space:
            glyphs.pop()
        visible = [g for g in glyphs if not g.is_space]
        row = Row(
            glyphs=glyphs,
            x0=min(g.x0 for g in visible),
            x1=max(g.x1 for g in visible),
            top=max(t for t, _, _, _ in grp),
            bottom=min(b for _, b, _, _ in grp),
            page=page_no,
        )
        row.size = statistics.median(g.size for g in visible)
        main = [g for g in visible if g.size >= 0.85 * row.size]
        row.baseline = statistics.median(g.y0 for g in main)
        for g in visible:
            if g.size <= 0.8 * row.size and g.y0 > row.baseline + 0.2 * row.size:
                g.sup = True
        rows.append(row)
    rows.sort(key=lambda r: -r.top)
    return rows


# --------------------------------------------------------------------------------------
# Reading order: columns
# --------------------------------------------------------------------------------------


def _column_groups(items, box):
    """Split a page's lines into reading-order groups: [(frame, [item, ...]), ...].

    Finds a gutter — a vertical strip near the middle that no column line crosses —
    and sorts the lines into full-width bands (titles, footnotes) and two-column bands
    between them; within a band the left column is read before the right. A page
    without a clear gutter comes back as one group with frame None.
    """
    if len(items) < 8:
        return [(None, items)]
    boxes = [box(it) for it in items]  # (x0, x1, top, bottom)
    X0 = min(b[0] for b in boxes)
    X1 = max(b[1] for b in boxes)
    W = X1 - X0
    if W <= 0:
        return [(None, items)]
    best = None
    x = X0 + 0.3 * W
    while x <= X0 + 0.7 * W:
        crossing = sum(1 for b in boxes if b[0] < x - 1 and b[1] > x + 1)
        if best is None or crossing < best[0]:
            best = (crossing, x, x)
        elif crossing == best[0] and abs(x - best[2] - 1) < 1e-6:
            best = (crossing, best[1], x)  # extend the run of equally good positions
        x += 1.0
    crossing, run_a, run_b = best
    gutter = (run_a + run_b) / 2
    left = [b for b in boxes if b[1] <= gutter]
    right = [b for b in boxes if b[0] >= gutter]
    wide = 0.25 * W
    if (
        sum(1 for b in left if b[1] - b[0] >= wide) < 4
        or sum(1 for b in right if b[1] - b[0] >= wide) < 4
        or len(left) + len(right) < 0.5 * len(items)
        # Columns are made of long lines; a table of contents broken into pieces at its
        # dot leaders is made of short ones.
        or sum(b[1] - b[0] for b in left) / len(left) < 0.3 * W
        or sum(b[1] - b[0] for b in right) / len(right) < 0.3 * W
    ):
        return [(None, items)]

    full_frame = (X0, X1)
    l_frame = (X0, gutter)
    r_frame = (gutter, X1)
    order = sorted(range(len(items)), key=lambda i: -boxes[i][2])
    groups: list[tuple[tuple[float, float] | None, list]] = []
    band_left: list = []
    band_right: list = []

    def flush_band():
        if band_left:
            groups.append((l_frame, list(band_left)))
        if band_right:
            groups.append((r_frame, list(band_right)))
        band_left.clear()
        band_right.clear()

    crossing_rows = [b for b in boxes if b[0] < gutter - 1 and b[1] > gutter + 1]

    def beside_full(b) -> bool:
        """A short line level with a full-width one (a folio beside the running head)."""
        for c in crossing_rows:
            overlap = min(b[2], c[2]) - max(b[3], c[3])
            if overlap > 0.5 * min(b[2] - b[3], c[2] - c[3]):
                return True
        return False

    for i in order:
        b = boxes[i]
        if (b[0] < gutter - 1 and b[1] > gutter + 1) or beside_full(b):
            flush_band()
            if groups and groups[-1][0] == full_frame:
                groups[-1][1].append(items[i])
            else:
                groups.append((full_frame, [items[i]]))
        elif b[1] <= gutter + 1:
            band_left.append(items[i])
        else:
            band_right.append(items[i])
    flush_band()
    return groups


# --------------------------------------------------------------------------------------
# Extraction
# --------------------------------------------------------------------------------------


def _scan_image(images, width: float, height: float):
    """The page's scan, if one image covers most of it."""
    if not images:
        return None
    big = max(images, key=lambda b: (b[2] - b[0]) * (b[3] - b[1]))
    area = (big[2] - big[0]) * (big[3] - big[1])
    return big if area >= 0.5 * width * height else None


def _ocr_available() -> bool:
    if shutil.which("tesseract") is None or shutil.which("pdftoppm") is None:
        return False
    import importlib.util

    return all(importlib.util.find_spec(m) for m in ("numpy", "pdf2image", "pytesseract"))


def _rows_from_scan(scan, page_no: int) -> list[Row]:
    """Rows of glyphs from ocr.scanpage lines (one row per OCR line)."""
    rows: list[Row] = []
    for line in scan.lines:
        glyphs: list[Glyph] = []
        size = line.size

        def raised(label: str, x: float) -> None:
            for ch in label:
                glyphs.append(Glyph(ch, size=0.6 * size, x0=x, x1=x,
                                    y0=line.baseline + 0.4 * size, sup=True))

        for k, w in enumerate(line.words):
            if not w.text and k > 0 and glyphs:
                # Tesseract split a reference figure off as its own 'word': attach it.
                while glyphs and glyphs[-1].is_space:
                    glyphs.pop()
                raised(w.sup_before or w.sup_after or "?", w.x0)
                continue
            if glyphs:
                glyphs.append(Glyph(" ", x0=glyphs[-1].x1, x1=w.x0, y0=line.baseline))
            if w.sup_before:
                raised(w.sup_before, w.x0)
                if w.text:
                    glyphs.append(Glyph(" ", x0=w.x0, x1=w.x0, y0=line.baseline))
            step = (w.x1 - w.x0) / max(len(w.text), 1)
            # The slant belongs to the letters: edge punctuation stays upright ('*G*,').
            alnum = [i for i, ch in enumerate(w.text) if ch.isalnum()]
            first, last = (alnum[0], alnum[-1]) if alnum else (0, -1)
            for i, ch in enumerate(w.text):
                glyphs.append(Glyph(ch, italic=w.italic and first <= i <= last, size=size,
                                    x0=w.x0 + i * step, x1=w.x0 + (i + 1) * step,
                                    y0=line.baseline, ocr=True))
            if w.sup_after:
                raised(w.sup_after, w.x1)
        while glyphs and glyphs[-1].is_space:
            glyphs.pop()
        if not glyphs:
            continue
        rows.append(Row(glyphs=glyphs, x0=line.x0, x1=line.x1, top=line.top,
                        bottom=line.bottom, page=page_no, size=size, baseline=line.baseline,
                        fuzzy=True))
    return rows


def extract_pages(
    path: str,
    pages: set[int] | None,
    ocr: bool = True,
    dpi: int = 400,
    lang: str = "eng",
    lexicon=None,
) -> tuple[list[Page], float]:
    """Read the PDF's pages into rows of styled glyphs; also return the share of glyphs
    drawn as invisible text (on pages that were not re-read by OCR)."""
    laparams = LAParams(all_texts=True)
    rsrc = PDFResourceManager()
    device = _StyledAggregator(rsrc, laparams=laparams)
    interpreter = PDFPageInterpreter(rsrc, device)
    out: list[Page] = []
    scans: list[tuple[Page, tuple, list]] = []
    with open(path, "rb") as fp:
        pagenos = {p - 1 for p in pages} if pages else None
        for idx, pdfpage in enumerate(PDFPage.get_pages(fp, pagenos=pagenos)):
            before = (device.glyphs, device.invisible_glyphs)
            interpreter.process_page(pdfpage)
            layout = device.get_result()
            page_no = (sorted(pagenos)[idx] + 1) if pagenos else idx + 1
            lines: list = []
            rules: list = []
            images: list = []
            _walk(layout, lines, rules, images)
            page = Page(number=page_no, width=layout.width, height=layout.height, rules=rules)
            image = _scan_image(images, layout.width, layout.height)
            if image is not None and ocr:
                # Keep the page's own OCR layer (text inside the scan) for the vote;
                # text outside it is an archive stamp ('This content downloaded ...').
                layer = []
                for ln in lines:
                    cx, cy = (ln.x0 + ln.x1) / 2, (ln.y0 + ln.y1) / 2
                    if image[0] <= cx <= image[2] and image[1] <= cy <= image[3]:
                        layer.append((ln.x0, ln.y0, ln.x1, ln.y1, ln.get_text().split()))
                page.scanned = True
                scans.append((page, image, layer))
                device.glyphs, device.invisible_glyphs = before  # judged by OCR instead
            else:
                for frame, group in _column_groups(lines, lambda ln: (ln.x0, ln.x1, ln.y1, ln.y0)):
                    for row in _build_rows(group, page_no):
                        row.frame = frame
                        page.rows.append(row)
            out.append(page)

    if scans:
        from pdf2image import convert_from_path

        from ocr.scanpage import Lexicon, read_scan_page

        lexicon = lexicon or Lexicon()
        for n, (page, image, layer) in enumerate(scans, 1):
            print(f"  OCR page {page.number} ({n}/{len(scans)})…", file=sys.stderr, flush=True)
            rendered = convert_from_path(path, dpi=dpi, first_page=page.number,
                                         last_page=page.number, grayscale=True)[0]
            s_x = rendered.size[0] / page.width
            s_y = rendered.size[1] / page.height
            crop = rendered.crop((
                int(image[0] * s_x), int((page.height - image[3]) * s_y),
                int(image[2] * s_x), int((page.height - image[1]) * s_y),
            ))
            scan = read_scan_page(crop, (image[0], image[3]), dpi, layer, lexicon, lang=lang)
            rows = _rows_from_scan(scan, page.number)
            for frame, group in _column_groups(rows, lambda r: (r.x0, r.x1, r.top, r.bottom)):
                for row in sorted(group, key=lambda r: -r.top):
                    row.frame = frame
                    page.rows.append(row)
            page.rules = scan.rules
    return out, device.invisible_glyphs / max(device.glyphs, 1)


# --------------------------------------------------------------------------------------
# Archive furniture: JSTOR cover pages and download stamps
# --------------------------------------------------------------------------------------

_STAMP = re.compile(
    r"This content downloaded from|All use subject to https?://about\.jstor\.org/terms"
    r"|^\(?cid:\d+\)|^\d{1,3}(\.\d{1,3}){3} on \w{3}, \d",
    re.I,
)


def _is_stamp(row: Row) -> bool:
    text = row.text
    if _STAMP.search(text):
        return True
    return text.count("(cid:") >= 3 and len(re.sub(r"\(cid:\d+\)", "", text).strip()) < 20


def jstor_front_matter(page: Page) -> dict | None:
    """Fields of a JSTOR cover page, or None if this isn't one."""
    text = "\n".join(r.text for r in page.rows)
    flat = re.sub(r"\s+", " ", text)
    if "Stable URL" not in flat or "JSTOR" not in flat or "Author(s)" not in flat:
        return None

    def between(a: str, b: str) -> str:
        m = re.search(re.escape(a) + r"\s*(.*?)\s*(?=" + b + ")", flat)
        return m.group(1).strip() if m else ""

    meta = {
        "title": flat.split("Author(s):")[0].strip(),
        "author": between("Author(s):", r"Source:"),
        "source": between("Source:", r"Published by:|Stable URL:"),
        "publisher": between("Published by:", r"Stable URL:"),
    }
    url = re.search(r"Stable URL:\s*(\S+)", flat)
    if url:
        meta["url"] = url.group(1)
    meta["source"] = re.sub(r"(\d)-\s+(\d)", r"\1-\2", meta["source"])
    return {k: v for k, v in meta.items() if v}


def _yaml_front_matter(meta: dict) -> str:
    """iA Writer metadata: '---', plain 'key: value' lines, '---' (no quoting — iA
    would show quotes as part of the value in [%title])."""
    lines = ["---"]
    for key in ("title", "author", "source", "publisher", "url"):
        if key in meta:
            lines.append(f"{key}: {' '.join(meta[key].split())}")
    lines.append("---")
    return "\n".join(lines)


# --------------------------------------------------------------------------------------
# Page furniture: running heads, folios, footnotes
# --------------------------------------------------------------------------------------

_FOLIO = re.compile(r"^(?:\d{1,4}|[ivxlcdm]{1,7}|[IVXLCDM]{1,7}|\d{2,3}[Il])$")


def _furniture_key(row: Row) -> str:
    return re.sub(r"[^a-z]", "", row.plain_text.lower())


def _folio_of(row: Row) -> str | None:
    tokens = row.plain_text.split()
    for t in (tokens[:1] + tokens[-1:]) if tokens else []:
        if _FOLIO.match(t):
            # Old-style figures: a scanned '341' often reads as '34I'.
            return re.sub(r"(?<=\d)[Il]$", "1", t)
    return None


def _edge_band(rows: list[Row], top: bool) -> int:
    """How many rows at the top (or bottom) of a page share the first (last) row's
    height band — a running head whose folio OCR read as a separate line."""
    if not rows:
        return 0
    seq = rows if top else rows[::-1]
    ref = seq[0]
    n = 1
    while n < len(seq) and abs(seq[n].baseline - ref.baseline) <= 0.5 * ref.size:
        n += 1
    return n


def _band_text(rows: list[Row]) -> str:
    return " ".join(r.plain_text for r in sorted(rows, key=lambda r: r.x0))


def strip_furniture(pages: list[Page], body: float) -> None:
    """Drop each page's running head (top band) and bottom folio, keeping the folio."""
    for page in pages:
        page.rows = [r for r in page.rows if not _is_stamp(r)]

    def key(text: str) -> str:
        return re.sub(r"[^a-z]", "", text.lower())

    tops = Counter(key(_band_text(p.rows[:_edge_band(p.rows, True)])) for p in pages if p.rows)
    bottoms = Counter(key(_band_text(p.rows[len(p.rows) - _edge_band(p.rows, False):]))
                      for p in pages if p.rows)

    for page in pages:
        if not page.rows:
            continue
        n = _edge_band(page.rows, True)
        band = page.rows[:n]
        text = _band_text(band)
        size = max(r.size for r in band)
        letters = [c for c in text if c.isalpha()]
        caps = bool(letters) and sum(c.isupper() for c in letters) >= 0.8 * len(letters)
        tokens = text.split()
        folio = next((re.sub(r"(?<=\d)[Il]$", "1", t) for t in (tokens[:1] + tokens[-1:])
                      if _FOLIO.match(t)), None)
        rest = page.rows[n:]
        # A running head stands apart: more space below it than between body lines.
        pitches = [a.baseline - b.baseline for a, b in zip(rest, rest[1:5])]
        detached = (
            len(rest) > 1
            and bool(pitches)
            and band[0].baseline - rest[0].baseline > 1.6 * statistics.median(pitches)
        )
        is_head = _size_class(band[0], body) != "h" and bool(rest) and (
            _FOLIO.match(text) is not None
            or (folio is not None and (caps or size <= 0.95 * body or detached))
            or (tops[key(text)] >= 2 and key(text) != "")
        )
        if is_head:
            page.folio = folio
            page.rows = rest
        if page.rows:
            n = _edge_band(page.rows, False)
            band = page.rows[len(page.rows) - n:]
            text = _band_text(band)
            tokens = text.split()
            folio = next((t for t in (tokens[:1] + tokens[-1:]) if _FOLIO.match(t)), None)
            if _FOLIO.match(text) or (
                bottoms[key(text)] >= 2 and key(text) != "" and len(text) < 80 and folio
            ):
                page.folio = page.folio or folio
                page.rows = page.rows[: len(page.rows) - n]


def _footnote_label(row: Row) -> tuple[str | None, int]:
    """Footnote label at the start of a row and the glyph index where its text begins."""
    vis = [(i, g) for i, g in enumerate(row.glyphs) if not g.is_space]
    if not vis:
        return None, 0
    # Superscript label: '¹See ...'
    if vis[0][1].sup:
        label = ""
        j = 0
        while j < len(vis) and vis[j][1].sup:
            label += vis[j][1].text
            j += 1
        if _MARKER_LABEL.match(label):
            return label, vis[j][0] if j < len(vis) else len(row.glyphs)
    # Full-size label: '1 See ...', '1. See ...', '* See ...'
    m = re.match(r"^(\d{1,3}|[*∗†‡]{1,3})(\.?)\s", row.text + " ")
    if m:
        n = len(m.group(1)) + len(m.group(2))
        return m.group(1), vis[n][0] if n < len(vis) else len(row.glyphs)
    return None, 0


def split_footnotes(page: Page, body: float) -> tuple[list[Row], list[Row]]:
    """Split a page's rows into (body rows, footnote rows).

    The footnote zone is the trailing run of rows set smaller than the body, but only
    if it is announced by a separator rule above it or opens with a footnote label —
    so a block quote in small type at the foot of a page stays in the body. Small rows
    just above the first label that sit flush with the notes' margin are the end of a
    note carried over from the previous page.
    """
    rows = page.rows
    small_from = len(rows)
    while small_from > 0 and _size_class(rows[small_from - 1], body) == "s":
        small_from -= 1
    # The zone may start below other small type (a verse quote just above the notes).
    for start in range(small_from, len(rows)):
        first = rows[start]
        above = rows[start - 1].bottom if start > 0 else float("inf")
        has_rule = any(first.top - 2 <= y <= above + 2 for _, _, y in page.rules)
        if has_rule and start > 0:
            return rows[:start], rows[start:]
        if _footnote_label(first)[0] is not None:
            margin = min(r.x0 for r in rows[start:])
            while (
                start > small_from
                and abs(rows[start - 1].x0 - margin) <= rows[start - 1].size
                and _footnote_label(rows[start - 1])[0] is None
            ):
                start -= 1
            return rows[:start], rows[start:]
    return rows, []


# --------------------------------------------------------------------------------------
# Paragraphs
# --------------------------------------------------------------------------------------


@dataclass
class Block:
    kind: str  # 'p', 'h' (heading), 'quote', 'item'; 'centered' while building
    rows: list[Row]
    level: int = 0
    page_mark: dict[int, str] = field(default_factory=dict)  # row index -> folio
    hang: float | None = None  # x of a list item's hanging indent


def _page_geometry(rows: list[Row], body: float) -> tuple[float, float]:
    """(left margin, right margin) of the body text in a page or column."""
    body_rows = [r for r in rows if _size_class(r, body) == "b"] or rows
    lefts = Counter(round(r.x0) for r in body_rows)
    left = min(x for x, n in lefts.items() if n == max(lefts.values()))
    rights = sorted(r.x1 for r in body_rows)
    right = rights[int(0.9 * (len(rights) - 1))]
    return float(left), float(right)


def _size_class(row: Row, body: float) -> str:
    """'h' display type, 's' small (notes, quotes), 'b' body. Sizes measured from a
    scan wobble by several percent, so they get wider margins than font sizes."""
    big, small = (1.2, 0.87) if row.fuzzy else (1.15, 0.92)
    if row.size >= big * body:
        return "h"
    if row.size <= small * body:
        return "s"
    return "b"


# A list label opening a row: '1.', '(ii)', 'a)', 'not-3.', or a display's 'Either' / 'or'.
_LIST_LABEL = re.compile(r"^(\d{1,2}\s?\.|not-\s?\d{1,2}\s?\.|\(?[ivx]{1,4}\)|\([a-z]\)|[a-z]\)|Either|or)\s+")
_NUM_LABEL = re.compile(r"^(\d{1,2}\s?\.|not-\s?\d{1,2}\s?\.)\s")
_ROMAN_HEADING = re.compile(r"^(?:[IVXL]{1,6}|[IVXL1l]*[Il1][IVXL1l]*)\.?$")


def _hang_x(row: Row) -> float | None:
    """Where the text after a list label begins, for hanging-indent continuation lines."""
    m = _LIST_LABEL.match(row.plain_text)
    if not m:
        return None
    count = 0
    for g in row.glyphs:
        if g.sup or g.marker is not None:
            continue
        if count >= m.end() and not g.is_space:
            return g.x0
        count += len(g.text)
    return None


def _roman_heading(row: Row) -> str | None:
    """'II' for a row that is just a section numeral (OCR reads III as 'Ill')."""
    text = row.plain_text.strip()
    if not _ROMAN_HEADING.match(text) or len(text) > 6:
        return None
    fixed = text.rstrip(".").replace("l", "I").replace("1", "I")
    return fixed if re.fullmatch(r"[IVXL]+", fixed) else None


def build_blocks(pages: list[Page], body_rows: dict[int, list[Row]], body: float, page_markers: bool):
    frames: dict[tuple, list[Row]] = {}
    for page in pages:
        for r in body_rows[page.number]:
            frames.setdefault((page.number, r.frame), []).append(r)
    geometry = {k: _page_geometry(v, body) for k, v in frames.items()}
    blocks: list[Block] = []
    cur: Block | None = None
    prev: Row | None = None

    def geom(r: Row) -> tuple[float, float]:
        return geometry[(r.page, r.frame)]

    pitches_by_frame = {}
    for key, rows in frames.items():
        p = [a.baseline - b.baseline for a, b in zip(rows, rows[1:])
             if _size_class(a, body) == _size_class(b, body) == "b" and a.baseline > b.baseline]
        pitches_by_frame[key] = statistics.median(p) if p else 1.2 * body

    for page in pages:
        rows = body_rows[page.number]
        for i, row in enumerate(rows):
            left, right = geom(row)
            frame = row.frame or (left, right)
            center = (frame[0] + frame[1]) / 2
            pitch = pitches_by_frame[(row.page, row.frame)]
            em = row.size
            cls = _size_class(row, body)
            gap_l, gap_r = row.x0 - max(left, frame[0]), min(right, frame[1]) - row.x1
            centered = (
                abs((row.x0 + row.x1) / 2 - center) < 1.5 * em
                and row.x1 - row.x0 < 0.7 * (frame[1] - frame[0])
                and gap_l > 2 * em
                and gap_r > 2 * em
                and abs(gap_l - gap_r) <= max(1.5 * em, 0.15 * (gap_l + gap_r))
            )
            # Pages skipped in between (--pages 10-12,40-41): never run text together.
            new = cur is None or prev is None or row.page - prev.page > 1
            if not new:
                prev_cls = _size_class(prev, body)
                same_frame = prev.page == row.page and prev.frame == row.frame
                p_left, p_right = geom(prev)
                hang = cur.hang if cur.hang is not None else (
                    _hang_x(cur.rows[0]) if len(cur.rows) == 1 else None)
                if cls != prev_cls and not (
                    row.fuzzy and abs(row.size - prev.size) <= 0.1 * max(row.size, prev.size)
                ):
                    new = True
                elif cls == "h":
                    new = i == 0 or prev.baseline - row.baseline > 2.0 * em
                elif centered or cur.kind == "centered":
                    new = True
                elif same_frame and prev.baseline - row.baseline > 1.45 * pitch:
                    new = True
                elif (
                    hang is not None
                    and same_frame
                    and cur.rows[0].x0 + 0.5 * em < row.x0 <= hang + 0.8 * em
                    and (cur.hang is None or abs(row.x0 - cur.hang) <= 0.8 * em)
                ):
                    new = False  # hanging indent under a list label
                    cur.hang = cur.hang if cur.hang is not None else row.x0
                elif cur.hang is not None and row.x0 < cur.hang - 0.5 * em:
                    new = True  # back out of the hanging indent: the item is over
                elif _NUM_LABEL.match(row.plain_text) and row.x0 > left + 0.5 * em:
                    new = True  # an indented '2.' or 'not-1.' opens the next premise
                elif row.x0 > (max(prev.x0, left) if same_frame else left) + 0.5 * em:
                    new = True  # first-line indent, or the start of a block quote
                elif (
                    same_frame
                    and len(cur.rows) >= 2
                    and all(r.x0 > geom(r)[0] + 0.5 * em and r.x1 < geom(r)[1] - 0.8 * em
                            for r in cur.rows)
                    and row.x0 < cur.rows[-1].x0 - 0.5 * em
                ):
                    new = True  # body resumes after an indented block quote
                else:
                    ends = prev.plain_text[-1:] in ".?!:\"”’)"
                    if prev.x1 < p_right - 2 * em and ends:
                        new = True
            if (
                prev is not None
                and cur is not None
                and (prev.page, prev.frame) != (row.page, row.frame)
                and cur.rows[0].x1 - cur.rows[0].x0 < 0.6 * (geom(cur.rows[0])[1] - geom(cur.rows[0])[0])
                and row.plain_text[:1].islower()
                and len(cur.rows) == 1
                and len(blocks) >= 2
                and blocks[-2].kind == "p"
                and blocks[-2].rows[-1].plain_text[-1:] not in ".?!:;”\""
                and not row.x0 > left + 0.5 * em
            ):
                # 'warmly' / 'Purdue University' / 'received by ...': the short line was
                # an affiliation or caption at the column foot; the sentence goes on.
                cur = blocks[-2]  # the short block stays after the paragraph it interrupted
                cur.rows.append(row)
                prev = row
                continue
            if new:
                kind = "h" if cls == "h" else ("centered" if centered else "p")
                cur = Block(kind=kind, rows=[])
                blocks.append(cur)
            if page_markers and i == 0:
                cur.page_mark[len(cur.rows)] = page.folio or f"pdf {page.number}"
            cur.rows.append(row)
            prev = row

    # Classify: headings by size rank, section numerals, list items, indented quotes.
    sizes = sorted({round(statistics.median(r.size for r in b.rows) * 2) / 2
                    for b in blocks if b.kind == "h"}, reverse=True)
    for b in blocks:
        if b.kind == "h":
            size = round(statistics.median(r.size for r in b.rows) * 2) / 2
            b.level = min(sizes.index(size) + 1, 4)
        elif b.kind == "centered":
            b.kind = "p"
            if len(b.rows) == 1 and _roman_heading(b.rows[0]):
                b.kind = "h"
                b.level = min(len(sizes) + 1, 4)
        elif _LIST_LABEL.match(b.rows[0].plain_text) and (len(b.rows) == 1 or b.hang is not None):
            b.kind = "item"
        elif len(b.rows) >= 2:
            if all(r.x0 > geom(r)[0] + 1.0 * r.size for r in b.rows[1:]) and all(
                r.x1 < geom(r)[1] - 0.8 * r.size for r in b.rows[:-1]
            ):
                b.kind = "quote"
    return blocks


# --------------------------------------------------------------------------------------
# Markdown rendering
# --------------------------------------------------------------------------------------

_KEEP_HYPHEN_PREFIXES = {"self", "non", "quasi", "half", "ill", "well", "all", "world"}
# 'in-' + 'itself', 'Being-' + 'for-self': a reflexive or already hyphenated tail
# marks a real compound, as in the Hegel translators' 'being-in-and-for-itself'.
_KEEP_HYPHEN_TAILS = {"itself", "oneself", "himself", "herself", "themselves", "self", "selves"}
_PRONOUNS = {"it", "him", "her", "them", "one", "my", "your", "our", "thy", "them"}
_STRIP = ".,;:!?()[]\"'“”‘’"
_LEXICON = None  # ocr.scanpage.Lexicon when a system word list is available


def _vocabulary(pages: list[Page]) -> tuple[set[str], set[str]]:
    """(words, hyphenated compounds) seen inside lines, i.e. not split by a line break."""
    words: set[str] = set()
    compounds: set[str] = set()
    for page in pages:
        for row in page.rows:
            for tok in row.plain_text.split()[1:-1]:
                tok = tok.strip(_STRIP).lower()
                if "-" in tok.strip("-"):
                    compounds.add(tok)
                    words.update(tok.split("-"))
                elif tok:
                    words.add(tok)
    return words, compounds


def _keep_line_end_hyphen(head: str, tail: str, vocab: tuple[set[str], set[str]]) -> bool:
    """Is 'head-' + 'tail' at a line break a real compound rather than hyphenation?"""
    words, compounds = vocab
    head = head.lower().strip(_STRIP)
    tail = tail.lower().strip(_STRIP)
    if f"{head}-{tail}" in compounds:
        return True
    if head + tail in words:
        return False
    if head in _KEEP_HYPHEN_PREFIXES or "-" in tail:
        return True
    if tail in _KEEP_HYPHEN_TAILS and head not in _PRONOUNS:
        return True
    if _LEXICON is not None and _LEXICON.has_dictionary:
        if _LEXICON.valid(head + tail):
            return False  # 'omnis-' + 'cient'
        if len(head) >= 2 and len(tail) >= 3 and _LEXICON.valid(head) and _LEXICON.valid(tail):
            return True  # 'so-' + 'called'

    # Two whole words the text uses on their own ('sequence-' + 'aligned'), joined
    # into a word it never uses: a compound.
    return len(head) >= 4 and len(tail) >= 4 and head in words and tail in words


def _join_rows(rows: list[Row], vocab, marks: dict[int, str] | None = None) -> list[Glyph]:
    """Concatenate rows into one glyph stream, undoing line-end hyphenation."""
    out: list[Glyph] = []
    for idx, row in enumerate(rows):
        glyphs = [g for g in row.glyphs if g.text != "­" or g is row.glyphs[-1]]
        if marks and idx in marks:
            if out and not out[-1].is_space:
                out.append(Glyph(" "))
            out.append(Glyph(f"{{p. {marks[idx]}}}"))
            glyphs = [Glyph(" ")] + glyphs
        if out:
            last = next((g for g in reversed(out) if not g.is_space), None)
            first = next((g for g in glyphs if not g.is_space), None)
            if (
                last is not None
                and first is not None
                and last.text in ("-", "­")
                and first.text[:1].isalpha()
                and first.text[:1].islower()
            ):
                # The word fragments either side of the break.
                head = ""
                for g in reversed(out[:-1]):
                    if g.is_space or g.marker is not None:
                        break
                    head = g.text + head
                tail = ""
                for g in glyphs:
                    if g.is_space or g.marker is not None:
                        break
                    tail += g.text
                keep = last.text == "-" and _keep_line_end_hyphen(head, tail, vocab)
                if not keep:
                    out.pop()
                out.extend(glyphs)
                continue
            if out[-1].is_space or (glyphs and glyphs[0].is_space):
                pass
            else:
                out.append(Glyph(" "))
        out.extend(glyphs)
    return [g if g.text != "­" else Glyph("") for g in out]


def _escape(text: str) -> str:
    """Backslash the characters that mean something in Markdown — including iA Writer's
    extras: ~sub~, ^sup^, ==highlight==, $math$, and [^ / [# / [% references."""
    text = re.sub(r"([\\*_`~^$])", r"\\\1", text)
    text = text.replace("==", "\\=\\=")
    return re.sub(r"\[(?=[\^#%])", r"\\[", text)


def _wrap(text: str, italic: bool, bold: bool) -> str:
    text = _escape(text)
    if not text.strip():
        return text
    mark = "***" if italic and bold else "**" if bold else "*" if italic else ""
    # Keep punctuation hugging the word outside the emphasis: '*Logic*,' and '(*OG*)'.
    if mark:
        m = re.fullmatch(r"([(\[“‘\"]*)(.*?[^\s)\]”’\"])([)\]”’\"]*)", text, re.S)
        if m and (m.group(1) or m.group(3)):
            return f"{m.group(1)}{mark}{m.group(2)}{mark}{m.group(3)}"
    return f"{mark}{text}{mark}"


def render_inline(glyphs: list[Glyph], footnote_ids: dict[str, int]) -> str:
    """Glyph stream -> Markdown inline text with emphasis and footnote references."""
    # Turn runs of superscript glyphs into footnote references (or iA's ^sup^ if unmatched).
    items: list[Glyph] = []
    i = 0
    while i < len(glyphs):
        g = glyphs[i]
        if g.sup and not g.is_space:
            label = ""
            note = g.note
            while i < len(glyphs) and glyphs[i].sup and not glyphs[i].is_space:
                label += glyphs[i].text
                i += 1
            if note is None and label in footnote_ids:
                note = footnote_ids[label]
            if note is not None:
                items.append(Glyph(f"[^{note}]", marker=label))
            elif label != "?":
                items.append(Glyph(f"^{label}^", marker=label))
            continue
        items.append(g)
        i += 1

    # Punctuation between two italic words is part of the italic run ('*God, Freedom,
    # and Evil*'), whatever style it was given on its own.
    solid = [k for k, g in enumerate(items) if g.marker is None and not g.is_space]
    for n, k in enumerate(solid):
        g = items[k]
        if not g.ocr or g.italic or g.text.isalnum() or n == 0 or n == len(solid) - 1:
            continue
        before, after = items[solid[n - 1]], items[solid[n + 1]]
        if before.italic and after.italic:
            items[k] = Glyph(g.text, italic=True, bold=g.bold, size=g.size, x0=g.x0, x1=g.x1,
                             y0=g.y0, sup=g.sup, marker=g.marker, note=g.note, ocr=True)

    out: list[str] = []
    run_text = ""
    run_style: tuple[bool, bool] | None = None
    pending_space = ""

    def flush():
        nonlocal run_text, run_style
        if run_text:
            out.append(_wrap(run_text, *(run_style or (False, False))))
        run_text, run_style = "", None

    for g in items:
        if g.marker is not None:
            flush()
            out.append(pending_space)
            pending_space = ""
            out.append(g.text)
            continue
        if g.is_space:
            if run_text or out:
                pending_space = " "
            continue
        style = (g.italic, g.bold)
        if style == run_style:
            run_text += pending_space + g.text
        else:
            flush()
            out.append(pending_space)
            run_text, run_style = g.text, style
        pending_space = ""
    flush()
    text = "".join(out)
    return re.sub(r" {2,}", " ", text).strip()


def _escape_block_start(text: str) -> str:
    """Keep a paragraph that happens to open like Markdown syntax from turning into it
    (in iA Writer also '//' comments, '/file' content blocks and '+++' page breaks)."""
    if re.match(r"^(#{1,6}\s|>|[-+*]\s|/|\+\+\+|\{\{)", text):
        return "\\" + text
    return re.sub(r"^(\d+)([.)]\s)", r"\1\\\2", text)


def _assign_note_refs(blocks: list[Block], notes_by_page: dict[int, list[tuple[str, int]]]) -> None:
    """Link each footnote reference in the body to its note.

    By label where the label reads clearly; otherwise by order — the n-th unclaimed
    reference on a page belongs to the n-th unclaimed note (a scanned '¹' that OCR
    read as an apostrophe still finds note 1).
    """
    claimed: set[int] = set()
    refs: list[tuple[int, Glyph, str]] = []  # (page, first glyph, label)
    for b in blocks:
        for row in b.rows:
            glyphs = row.glyphs
            i = 0
            while i < len(glyphs):
                if glyphs[i].sup and not glyphs[i].is_space:
                    first, label = glyphs[i], ""
                    while i < len(glyphs) and glyphs[i].sup and not glyphs[i].is_space:
                        label += glyphs[i].text
                        i += 1
                    refs.append((row.page, first, label))
                else:
                    i += 1
    unresolved = []
    for page, g, label in refs:
        for lab, nid in notes_by_page.get(page, []):
            if lab == label and nid not in claimed and label != "?":
                g.note = nid
                claimed.add(nid)
                break
        else:
            unresolved.append((page, g, label))
    for page, g, label in unresolved:
        if not re.fullmatch(r"\d{1,3}|\?|[*∗†‡]+", label):
            continue  # a real superscript ('2nd', 'x²'), not a reference
        for pg in (page, page + 1, page - 1):
            free = [nid for _, nid in notes_by_page.get(pg, []) if nid not in claimed]
            if free:
                g.note = free[0]
                claimed.add(free[0])
                break


def _tidy(text: str, ocr: bool = True) -> str:
    """OCR spacing and quote repairs on a rendered paragraph (typeset text is left be)."""
    if not ocr:
        return text
    text = re.sub(r"\bnot-\s+(?=[\dpqr]\b)", "not-", text)  # 'not- 1' -> 'not-1'
    text = re.sub(r"\(\s*([\w.-]{1,8}?)\s*\)", r"(\1)", text)  # '( 1 )' -> '(1)'
    text = re.sub(r"\)\s+([.,;:])(?=\s|$)", r")\1", text)  # '(1) .' -> '(1).'
    # A speck after a little word: 'justified in. maintaining'.
    text = re.sub(r"\b(in|of|the|and|to|is|it|an|on|as|at|by|or|be|that|with)\.(?= [a-z])", r"\1", text)
    # Balance double quotes: a curly double quote opened and closed with a single one.
    out, open_double, open_single = [], False, False
    for i, ch in enumerate(text):
        nxt = text[i + 1] if i + 1 < len(text) else " "
        prv = text[i - 1] if i else " "
        if ch == "“":
            open_double = True
        elif ch == "”":
            open_double = False
        elif ch == "‘" and not prv.isalpha():
            open_single = True
        elif ch == "’" and open_single and not nxt.isalpha():
            open_single = False  # a nested 'single' quotation closing
        elif ch == "’" and open_double and not nxt.isalpha() and not prv.isspace():
            ch, open_double = "”", False
        elif ch == "‘" and not open_double and prv in " (\n" and "”" in text[i:i + 80].split("“")[0] \
                and "’" not in text[i + 1:i + 80].split("”")[0]:
            ch, open_double = "“", True
        out.append(ch)
    return "".join(out)


def _harmonize_variables(pages: list[Page]) -> None:
    """Make OCR'd one-to-three-capital symbols (G, OG, E) italic everywhere if they are
    mostly italic: variables are set consistently, and the slant test misses a few."""
    words: dict[str, list[list[Glyph]]] = {}
    for page in pages:
        for row in page.rows:
            if not row.fuzzy:
                continue
            run: list[Glyph] = []
            for g in row.glyphs + [Glyph(" ")]:
                if g.is_space or g.sup:
                    core = [x for x in run if x.text.isalpha()]
                    key = "".join(x.text for x in core)
                    initial = len(key) == 1 and run and run[-1].text == "."  # 'G. E. Moore'
                    if core and len(key) <= 3 and key.isupper() and not initial:
                        words.setdefault(key, []).append(core)
                    run = []
                else:
                    run.append(g)
    for occurrences in words.values():
        italic = sum(1 for occ in occurrences if all(g.italic for g in occ))
        if len(occurrences) >= 3 and italic >= 0.6 * len(occurrences):
            for occ in occurrences:
                for g in occ:
                    g.italic = True


def _letters(s: str) -> str:
    return re.sub(r"[^a-z]", "", s.lower())


def _block_text_fixups(text: str, block: Block, meta: dict | None) -> str:
    """Small presentational repairs on a rendered block."""
    if block.kind == "h" and meta and meta.get("title"):
        t = _letters(meta["title"])
        if t and _letters(text).endswith(t):
            prefix = re.match(r"^((?:[IVXLC]+|\d+)\.\s+)?", text).group(0)
            return prefix + meta["title"]
    if block.kind == "p" and meta and meta.get("author") and _letters(text) == _letters(meta["author"]):
        return meta["author"]
    # Drop cap followed by small capitals: 'THIS paper is ...' -> 'This paper is ...'.
    m = re.match(r"^([A-Z])([A-Z]{2,})(?= [a-z])", text)
    if m and block.kind == "p":
        text = m.group(1) + m.group(2).lower() + text[m.end():]
    return text


def to_markdown(pages: list[Page], page_markers: bool = False) -> str:
    meta = None
    kept: list[Page] = []
    for page in pages:
        m = jstor_front_matter(page) if not page.scanned else None
        if m and meta is None:
            meta = m
            continue
        kept.append(page)
    pages = kept

    sizes = Counter()
    for page in pages:
        for row in page.rows:
            for g in row.glyphs:
                if not g.is_space and not g.sup:
                    sizes[round(g.size * 2) / 2] += 1
    if not sizes:
        return _yaml_front_matter(meta) + "\n" if meta else ""
    body = sizes.most_common(1)[0][0]

    strip_furniture(pages, body)
    _harmonize_variables(pages)
    vocab = _vocabulary(pages)

    # Footnotes per page, numbered 1, 2, 3 ... through the whole output.
    body_rows: dict[int, list[Row]] = {}
    notes: list[tuple[int, list[Row]]] = []  # (id, rows)
    page_note_ids: dict[int, dict[str, int]] = {}
    notes_by_page: dict[int, list[tuple[str, int]]] = {}
    next_id = 1
    for page in pages:
        main, foot = split_footnotes(page, body)
        body_rows[page.number] = main
        ids: dict[str, int] = {}
        for row in foot:
            label, start = _footnote_label(row)
            if label is None:
                if notes:
                    notes[-1][1].append(row)  # continued from the previous page or line
                continue
            trimmed = Row(row.glyphs[start:], row.x0, row.x1, row.top, row.bottom, row.page,
                          row.size, row.baseline, row.frame, row.fuzzy)
            if label != "?":
                ids[label] = next_id
            notes_by_page.setdefault(page.number, []).append((label, next_id))
            notes.append((next_id, [trimmed]))
            next_id += 1
        page_note_ids[page.number] = ids

    blocks = build_blocks(pages, body_rows, body, page_markers)
    _assign_note_refs(blocks, notes_by_page)
    parts: list[str] = [_yaml_front_matter(meta)] if meta else []
    seen_heading = False
    for b in blocks:
        seen_heading = seen_heading or b.kind == "h"
        if meta and not seen_heading and re.match(r"^Vol(ume|\.)\s*\d", _band_text(b.rows)):
            continue  # the journal's issue line; the front matter has it
        # Notes on the block's own pages win; a neighbouring page is the fallback for a
        # note that the typesetter pushed to the next page (or a marker that ran over).
        ids: dict[str, int] = {}
        for pg in sorted({r.page for r in b.rows}):
            ids = {**page_note_ids.get(pg - 1, {}), **page_note_ids.get(pg + 1, {}), **ids}
        for r in b.rows:
            ids.update(page_note_ids.get(r.page, {}))
        ocr = any(r.fuzzy for r in b.rows)
        marks = dict(b.page_mark)
        if b.kind == "h" and 0 in marks:
            parts.append(f"{{p. {marks.pop(0)}}}")
        glyphs = _join_rows(b.rows, vocab, marks)
        if b.kind == "h":
            for g in glyphs:  # the heading mark already says it is display type
                g.bold = False
            if len(b.rows) == 1 and _roman_heading(b.rows[0]):
                text = _roman_heading(b.rows[0])
            else:
                text = render_inline(glyphs, ids)
            text = _block_text_fixups(text, b, meta)
            # iA Writer reads a heading's closing '[...]' as a cross-reference label.
            text = re.sub(r"\[([^\]]*)\]$", r"\\[\1]", text)
            parts.append("#" * b.level + " " + text)
        elif b.kind == "quote":
            parts.append("> " + _escape_block_start(_tidy(render_inline(glyphs, ids), ocr)))
        elif b.kind == "item" and re.match(r"^\d{1,2}\s?\.", b.rows[0].plain_text):
            text = _tidy(render_inline(glyphs, ids), ocr)
            parts.append(re.sub(r"^(\d{1,2})\s?\.\s*", r"\1. ", text))
        else:
            text = _block_text_fixups(_tidy(render_inline(glyphs, ids), ocr), b, meta)
            parts.append(_escape_block_start(text))

    for nid, rows in notes:
        parts.append(f"[^{nid}]: " + _tidy(render_inline(_join_rows(rows, vocab), {}),
                                           any(r.fuzzy for r in rows)))
    return "\n\n".join(p for p in parts if p.strip()) + "\n"


# --------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------


def _parse_pages(spec: str | None) -> set[int] | None:
    if not spec:
        return None
    pages: set[int] = set()
    for part in spec.split(","):
        if "-" in part:
            a, b = part.split("-", 1)
            pages.update(range(int(a), int(b) + 1))
        else:
            pages.add(int(part))
    return pages


def _warn_about_text_layer(pages: list[Page], invisible_share: float, ocr_used: bool) -> None:
    text = "".join(r.text for p in pages if not p.scanned for r in p.rows if not _is_stamp(r))
    if text.strip() and invisible_share > 0.5 and not ocr_used:
        print(
            "WARNING: the text is invisible text over page images — an OCR layer, not "
            "typesetting — so it carries no italics. Install tesseract (and leave out "
            "--no-ocr) to read the scans themselves.",
            file=sys.stderr,
        )
    elif not text.strip() and not any(p.scanned for p in pages):
        print(
            "WARNING: no text found. This looks like a scan; install tesseract and "
            "poppler so the pages can be read by OCR.",
            file=sys.stderr,
        )
    elif text.count("(cid:") > 20:
        print(
            "WARNING: many glyphs have no Unicode mapping ('(cid:NN)' in the output); "
            "this PDF's text layer is partly broken.",
            file=sys.stderr,
        )


def main() -> int:
    global _LEXICON
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("input", help="PDF to convert")
    parser.add_argument("-o", "--output", help="Markdown file to write (default: input name .md)")
    parser.add_argument("--pages", help="PDF pages to convert, e.g. 12-18 or 3,5,9-11")
    parser.add_argument(
        "--page-markers",
        action="store_true",
        help="Insert the printed page number as {p. 25} where each page begins",
    )
    parser.add_argument(
        "--no-ocr",
        action="store_true",
        help="Don't OCR scanned pages; use the PDF's own (invisible) text layer as is",
    )
    parser.add_argument("--dpi", type=int, default=400, help="OCR resolution (default 400)")
    parser.add_argument("--lang", default="eng", help="Tesseract language(s) (default eng)")
    parser.add_argument("--dictionary", help="Word list for the OCR vote (default: system list)")
    args = parser.parse_args()

    ocr = not args.no_ocr and _ocr_available()
    if not args.no_ocr and not ocr:
        print("NOTE: tesseract/poppler not found — scanned pages use their own text layer.",
              file=sys.stderr)
    lexicon = None
    try:
        from ocr.scanpage import Lexicon

        lexicon = Lexicon(args.dictionary)
        _LEXICON = lexicon
    except ImportError:
        pass

    try:
        pages, invisible_share = extract_pages(args.input, _parse_pages(args.pages), ocr=ocr,
                                               dpi=args.dpi, lang=args.lang, lexicon=lexicon)
    except Exception as exc:
        name = type(exc).__name__
        if "Encryption" in name or "Password" in name:
            print(f"ERROR: the PDF is encrypted ({name}); DRM-protected files can't be read.",
                  file=sys.stderr)
            return 1
        raise
    _warn_about_text_layer(pages, invisible_share, ocr)

    output = args.output or str(Path(args.input).with_suffix(".md"))
    markdown = to_markdown(pages, page_markers=args.page_markers)
    Path(output).write_text(markdown, encoding="utf-8")
    print(f"Wrote {output} ({len(pages)} page(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
