#!/usr/bin/env python3
"""Turn a PDF with a real (typeset) text layer into Markdown, keeping italics.

For born-digital PDFs — e-book style, typeset from a text source — not for scans.
The text layer of such a PDF names the font of every glyph, so italic and bold
come straight from the typesetting instead of being guessed from the image:

  - italic / bold          -> *italic*, **bold**, ***both***
  - larger type            -> # headings (levels by size)
  - footnote markers       -> [^1] with the note text as [^1]: ... at the end
  - running heads, folios  -> dropped (page numbers optionally kept, --page-markers)
  - indented block quotes  -> > quote
  - line-end hyphenation   -> joined ('specu-' + 'lative' -> 'speculative'),
                              keeping real compounds seen elsewhere ('self-consciousness')

Do not run run_tesseract.py on such a PDF first: it rebuilds the pages from images
and throws this text layer — and with it the italics — away.

Usage:
    python pdf_to_markdown.py book.pdf                  # writes book.md
    python pdf_to_markdown.py book.pdf -o ote.md --pages 12-18
    python pdf_to_markdown.py book.pdf --page-markers   # adds {p. 25} at page breaks
"""

from __future__ import annotations

import argparse
import re
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
_MARKER_LABEL = re.compile(r"^(?:\d{1,3}|[*∗†‡§¶]{1,3}|[a-z])$")


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
    rows: list[Row] = field(default_factory=list)
    rules: list[tuple[float, float, float]] = field(default_factory=list)  # (x0, x1, y)
    folio: str | None = None  # printed page number, if found


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


def _walk(obj, lines, rules):
    if isinstance(obj, LTTextLineHorizontal):
        lines.append(obj)
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
        _walk(child, lines, rules)


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


def extract_pages(path: str, pages: set[int] | None) -> tuple[list[Page], float]:
    """Read the PDF's pages into rows of styled glyphs; also return the share of glyphs
    drawn as invisible text."""
    laparams = LAParams(all_texts=True)
    rsrc = PDFResourceManager()
    device = _StyledAggregator(rsrc, laparams=laparams)
    interpreter = PDFPageInterpreter(rsrc, device)
    out: list[Page] = []
    with open(path, "rb") as fp:
        pagenos = {p - 1 for p in pages} if pages else None
        for idx, pdfpage in enumerate(PDFPage.get_pages(fp, pagenos=pagenos)):
            interpreter.process_page(pdfpage)
            layout = device.get_result()
            page_no = (sorted(pagenos)[idx] + 1) if pagenos else idx + 1
            lines: list = []
            rules: list = []
            _walk(layout, lines, rules)
            page = Page(number=page_no, width=layout.width, rules=rules)
            page.rows = _build_rows(lines, page_no)
            out.append(page)
    return out, device.invisible_glyphs / max(device.glyphs, 1)


# --------------------------------------------------------------------------------------
# Page furniture: running heads, folios, footnotes
# --------------------------------------------------------------------------------------

_FOLIO = re.compile(r"^(?:\d{1,4}|[ivxlcdm]{1,7}|[IVXLCDM]{1,7})$")


def _furniture_key(row: Row) -> str:
    return re.sub(r"[^a-z]", "", row.plain_text.lower())


def _folio_of(row: Row) -> str | None:
    tokens = row.plain_text.split()
    for t in (tokens[:1] + tokens[-1:]) if tokens else []:
        if _FOLIO.match(t):
            return t
    return None


def strip_furniture(pages: list[Page], body: float) -> None:
    """Drop each page's running head (top row) and bottom folio, keeping the folio."""
    tops = Counter(_furniture_key(p.rows[0]) for p in pages if p.rows)
    bottoms = Counter(_furniture_key(p.rows[-1]) for p in pages if p.rows)

    for page in pages:
        if not page.rows:
            continue
        head = page.rows[0]
        text = head.plain_text
        letters = [c for c in text if c.isalpha()]
        caps = bool(letters) and sum(c.isupper() for c in letters) >= 0.8 * len(letters)
        folio = _folio_of(head)
        # A running head stands apart: more space below it than between body lines.
        pitches = [a.baseline - b.baseline for a, b in zip(page.rows[1:], page.rows[2:6])]
        detached = (
            len(page.rows) > 2
            and bool(pitches)
            and head.baseline - page.rows[1].baseline > 1.6 * statistics.median(pitches)
        )
        is_head = head.size < 1.15 * body and len(page.rows) > 1 and (
            _FOLIO.match(text) is not None
            or (folio is not None and (caps or head.size <= 0.95 * body or detached))
            or (tops[_furniture_key(head)] >= 2 and _furniture_key(head) != "")
        )
        if is_head:
            page.folio = folio
            page.rows.pop(0)
        if page.rows:
            foot = page.rows[-1]
            if _FOLIO.match(foot.plain_text) or (
                bottoms[_furniture_key(foot)] >= 2
                and _furniture_key(foot) != ""
                and len(foot.plain_text) < 80
                and _folio_of(foot)
            ):
                page.folio = page.folio or _folio_of(foot)
                page.rows.pop()


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
    so a block quote in small type at the foot of a page stays in the body.
    """
    rows = page.rows
    small_from = len(rows)
    while small_from > 0 and rows[small_from - 1].size <= 0.92 * body:
        small_from -= 1
    # The zone may start below other small type (a verse quote just above the notes).
    for start in range(small_from, len(rows)):
        first = rows[start]
        above = rows[start - 1].bottom if start > 0 else float("inf")
        has_rule = any(first.top - 2 <= y <= above + 2 for _, _, y in page.rules)
        if (has_rule and start > 0) or _footnote_label(first)[0] is not None:
            return rows[:start], rows[start:]
    return rows, []


# --------------------------------------------------------------------------------------
# Paragraphs
# --------------------------------------------------------------------------------------


@dataclass
class Block:
    kind: str  # 'p', 'h' (heading), 'quote'; 'centered' while building
    rows: list[Row]
    level: int = 0
    page_mark: dict[int, str] = field(default_factory=dict)  # row index -> folio


def _page_geometry(rows: list[Row], body: float) -> tuple[float, float]:
    """(left margin, right margin) of the body text on one page."""
    body_rows = [r for r in rows if 0.92 * body < r.size < 1.15 * body] or rows
    lefts = Counter(round(r.x0) for r in body_rows)
    left = min(x for x, n in lefts.items() if n == max(lefts.values()))
    rights = sorted(r.x1 for r in body_rows)
    right = rights[int(0.9 * (len(rights) - 1))]
    return float(left), float(right)


def _size_class(row: Row, body: float) -> str:
    if row.size >= 1.15 * body:
        return "h"
    if row.size <= 0.92 * body:
        return "s"
    return "b"


def build_blocks(pages: list[Page], body_rows: dict[int, list[Row]], body: float, page_markers: bool):
    geometry = {
        page.number: _page_geometry(body_rows[page.number], body)
        for page in pages
        if body_rows[page.number]
    }
    blocks: list[Block] = []
    cur: Block | None = None
    prev: Row | None = None
    prev_geom = (0.0, 0.0)

    for page in pages:
        rows = body_rows[page.number]
        if not rows:
            continue
        left, right = geometry[page.number]
        center = (left + right) / 2
        pitches = [a.baseline - b.baseline for a, b in zip(rows, rows[1:])
                   if _size_class(a, body) == _size_class(b, body) == "b"]
        pitch = statistics.median(pitches) if pitches else 1.2 * body

        for i, row in enumerate(rows):
            em = row.size
            cls = _size_class(row, body)
            centered = (
                abs((row.x0 + row.x1) / 2 - center) < 1.5 * em
                and row.x1 - row.x0 < 0.7 * (right - left)
                and row.x0 > left + 2 * em
            )
            # Pages skipped in between (--pages 10-12,40-41): never run text together.
            new = cur is None or prev is None or row.page - prev.page > 1
            if not new:
                prev_cls = _size_class(prev, body)
                if cls != prev_cls:
                    new = True
                elif cls == "h":
                    new = i == 0 or prev.baseline - row.baseline > 2.0 * em
                elif centered or cur.kind == "centered":
                    new = True
                else:
                    same_page = prev.page == row.page
                    if same_page and prev.baseline - row.baseline > 1.45 * pitch:
                        new = True
                    elif row.x0 > (max(prev.x0, left) if same_page else left) + 0.5 * em:
                        new = True  # first-line indent, or the start of a block quote
                    elif (
                        len(cur.rows) >= 2
                        and cur.rows[1].page == row.page
                        and row.x0 < cur.rows[1].x0 - 0.5 * em
                        and cur.rows[1].x0 > left + 0.5 * em
                    ):
                        new = True  # body resumes after an indented block quote
                    else:
                        p_right = right if same_page else prev_geom[1]
                        ends = prev.plain_text[-1:] in ".?!:\"”’)"
                        if prev.x1 < p_right - 2 * em and ends:
                            new = True
            if new:
                kind = "h" if cls == "h" else ("centered" if centered else "p")
                cur = Block(kind=kind, rows=[])
                blocks.append(cur)
            if page_markers and i == 0:
                cur.page_mark[len(cur.rows)] = page.folio or f"pdf {page.number}"
            cur.rows.append(row)
            prev = row
        prev_geom = (left, right)

    # Classify: headings by size rank, indented multi-row blocks as quotes.
    sizes = sorted({round(statistics.median(r.size for r in b.rows) * 2) / 2
                    for b in blocks if b.kind == "h"}, reverse=True)
    for b in blocks:
        if b.kind == "h":
            size = round(statistics.median(r.size for r in b.rows) * 2) / 2
            b.level = min(sizes.index(size) + 1, 4)
        elif b.kind == "centered":
            b.kind = "p"
        elif len(b.rows) >= 2:
            if all(r.x0 > geometry[r.page][0] + 1.0 * r.size for r in b.rows[1:]):
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
    # Two whole words the text uses on their own ('sequence-' + 'aligned'), joined
    # into a word it never uses: a compound.
    return len(head) >= 4 and len(tail) >= 4 and head in words and tail in words


def _join_rows(rows: list[Row], vocab, marks: dict[int, str] | None = None) -> list[Glyph]:
    """Concatenate rows into one glyph stream, undoing line-end hyphenation."""
    out: list[Glyph] = []
    for idx, row in enumerate(rows):
        glyphs = [g for g in row.glyphs if g.text != "\u00ad" or g is row.glyphs[-1]]
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
                and last.text in ("-", "\u00ad")
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
    return [g if g.text != "\u00ad" else Glyph("") for g in out]


def _escape(text: str) -> str:
    return re.sub(r"([\\*_`])", r"\\\1", text)


def _wrap(text: str, italic: bool, bold: bool) -> str:
    text = _escape(text)
    if not text.strip():
        return text
    mark = "***" if italic and bold else "**" if bold else "*" if italic else ""
    return f"{mark}{text}{mark}"


def render_inline(glyphs: list[Glyph], footnote_ids: dict[str, int]) -> str:
    """Glyph stream -> Markdown inline text with emphasis and footnote references."""
    # Turn runs of superscript glyphs into footnote references (or <sup> if unmatched).
    items: list[Glyph] = []
    i = 0
    while i < len(glyphs):
        g = glyphs[i]
        if g.sup and not g.is_space:
            label = ""
            while i < len(glyphs) and glyphs[i].sup and not glyphs[i].is_space:
                label += glyphs[i].text
                i += 1
            if label in footnote_ids:
                items.append(Glyph(f"[^{footnote_ids[label]}]", marker=label))
            else:
                items.append(Glyph(f"<sup>{label}</sup>", marker=label))
            continue
        items.append(g)
        i += 1

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
    """Keep a paragraph that happens to open like Markdown syntax from turning into it."""
    if re.match(r"^(#{1,6}\s|>|[-+*]\s)", text):
        return "\\" + text
    return re.sub(r"^(\d+)([.)]\s)", r"\1\\\2", text)


def to_markdown(pages: list[Page], page_markers: bool = False) -> str:
    sizes = Counter()
    for page in pages:
        for row in page.rows:
            for g in row.glyphs:
                if not g.is_space and not g.sup:
                    sizes[round(g.size * 2) / 2] += 1
    if not sizes:
        return ""
    body = sizes.most_common(1)[0][0]

    vocab = _vocabulary(pages)
    strip_furniture(pages, body)

    # Footnotes per page, numbered 1, 2, 3 ... through the whole output.
    body_rows: dict[int, list[Row]] = {}
    notes: list[tuple[int, list[Row]]] = []  # (id, rows)
    page_note_ids: dict[int, dict[str, int]] = {}
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
                          row.size, row.baseline)
            ids[label] = next_id
            notes.append((next_id, [trimmed]))
            next_id += 1
        page_note_ids[page.number] = ids

    blocks = build_blocks(pages, body_rows, body, page_markers)
    parts: list[str] = []
    for b in blocks:
        # Notes on the block's own pages win; a neighbouring page is the fallback for a
        # note that the typesetter pushed to the next page (or a marker that ran over).
        ids: dict[str, int] = {}
        for pg in sorted({r.page for r in b.rows}):
            ids = {**page_note_ids.get(pg - 1, {}), **page_note_ids.get(pg + 1, {}), **ids}
        for r in b.rows:
            ids.update(page_note_ids.get(r.page, {}))
        marks = dict(b.page_mark)
        if b.kind == "h" and 0 in marks:
            parts.append(f"{{p. {marks.pop(0)}}}")
        glyphs = _join_rows(b.rows, vocab, marks)
        if b.kind == "h":
            for g in glyphs:  # the heading mark already says it is display type
                g.bold = False
            parts.append("#" * b.level + " " + render_inline(glyphs, ids))
        elif b.kind == "quote":
            parts.append("> " + _escape_block_start(render_inline(glyphs, ids)))
        else:
            parts.append(_escape_block_start(render_inline(glyphs, ids)))

    for nid, rows in notes:
        parts.append(f"[^{nid}]: " + render_inline(_join_rows(rows, vocab), {}))
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


def _warn_about_text_layer(pages: list[Page], invisible_share: float) -> None:
    text = "".join(r.text for p in pages for r in p.rows)
    if text.strip() and invisible_share > 0.5:
        print(
            "WARNING: the text is invisible text over page images — an OCR layer, not "
            "typesetting — so it carries no italics, and headings and footnotes may be "
            "missed too.",
            file=sys.stderr,
        )
    elif not text.strip():
        print(
            "WARNING: no text layer found. This looks like a scan — OCR it first "
            "(run_tesseract.py); italics can't be recovered from a scan this way.",
            file=sys.stderr,
        )
    elif text.count("(cid:") > 20:
        print(
            "WARNING: many glyphs have no Unicode mapping ('(cid:NN)' in the output); "
            "this PDF's text layer is partly broken.",
            file=sys.stderr,
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("input", help="PDF with a typeset text layer")
    parser.add_argument("-o", "--output", help="Markdown file to write (default: input name .md)")
    parser.add_argument("--pages", help="PDF pages to convert, e.g. 12-18 or 3,5,9-11")
    parser.add_argument(
        "--page-markers",
        action="store_true",
        help="Insert the printed page number as {p. 25} where each page begins",
    )
    args = parser.parse_args()

    try:
        pages, invisible_share = extract_pages(args.input, _parse_pages(args.pages))
    except Exception as exc:
        name = type(exc).__name__
        if "Encryption" in name or "Password" in name:
            print(f"ERROR: the PDF is encrypted ({name}); DRM-protected files can't be read.",
                  file=sys.stderr)
            return 1
        raise
    _warn_about_text_layer(pages, invisible_share)

    output = args.output or str(Path(args.input).with_suffix(".md"))
    markdown = to_markdown(pages, page_markers=args.page_markers)
    Path(output).write_text(markdown, encoding="utf-8")
    print(f"Wrote {output} ({len(pages)} page(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
