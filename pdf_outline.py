#!/usr/bin/env python3
"""Build outline.md draft from the printed TOC pages of a text-layered PDF.

Same idea as parse_printed_toc.py — cluster TOC lines by (prefix class,
indent) and rank them — but reads from the PDF's existing text layer
instead of rasterizing + OCRing the page. Faster, and typographically
cleaner: no roman-numeral OCR misreads, no footnote-marker contamination,
no font-size guesswork.

Use this when:
  - your PDF already has a text layer (e.g. you've run run_tesseract.py)
  - and its printed table-of-contents pages carry more detail than the
    EPUB's nav (sub-sections, lettered subdivisions, greek subsubsections)

The text layer feeds the same hierarchy logic as parse_printed_toc.py:
each line gets (prefix_class, indent_bucket); styles are ordered by indent
ascending, with prefix-class rank as tiebreaker. Nothing is hardcoded to
a particular book's scheme.

Lines without a recognized numbering prefix (chapter titles like 'Preface',
'Introduction', and any prose-summary noise) are still emitted with their
indent-derived level — review the draft by hand and drop the noise rows.

Usage:
    python pdf_outline.py inwood2.pdf --toc-pages 25-27 > outline.md
    python pdf_outline.py inwood2.pdf --toc-pages 25-27 --indent-bucket 12
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from dataclasses import dataclass

from pypdf import PdfReader


# Numbering prefix classification. Same shape labels as parse_printed_toc.py;
# the level each maps to is learned from the document, not hardcoded.
_PREFIX_PATTERNS = [
    ("paren_double_upper", re.compile(r"^\(([A-Z])\1\.\)")),
    ("paren_double_lower", re.compile(r"^\(([a-z])\1\.\)")),
    ("arabic_dotted",      re.compile(r"^\d+\.\d+(?:\.\d+)*(?:\s|$)")),
    ("arabic",             re.compile(r"^\d+\.(?:\s|$)")),
    ("roman",              re.compile(r"^[IVX]+\.(?:\s|$)")),
    ("letter_upper",       re.compile(r"^[A-Z]\.(?:\s|$)")),
    ("letter_lower",       re.compile(r"^[a-z]\.(?:\s|$)")),
    ("greek_lower",        re.compile(r"^[αβγδεζηθικ]\.(?:\s|$)")),
]


def _classify_prefix(text: str) -> str:
    for name, pat in _PREFIX_PATTERNS:
        if pat.match(text):
            return name
    return "none"


_PAGE_NUMBER_RE = re.compile(r"\s+\.{0,}\s*(\d{1,4})\s*$")


def _split_page_number(text: str) -> tuple[str, int | None]:
    m = _PAGE_NUMBER_RE.search(text)
    if not m:
        return text.strip(), None
    head = text[: m.start()].rstrip(" .")
    return head, int(m.group(1))


@dataclass
class TocLine:
    text: str
    page_hint: int | None
    indent: float
    prefix: str


def parse_page_range(spec: str) -> list[int]:
    if "-" in spec:
        a, b = spec.split("-", 1)
        return list(range(int(a), int(b) + 1))
    return [int(spec)]


def collect_from_text_layer(pdf_path: str, pages: list[int], y_tol: float) -> list[TocLine]:
    """Read TOC pages from the PDF text layer; group shows into lines, return TocLines."""
    reader = PdfReader(pdf_path)
    out: list[TocLine] = []
    for page_no in pages:
        if page_no < 1 or page_no > len(reader.pages):
            print(f"skipping page {page_no}: out of range", file=sys.stderr)
            continue
        page = reader.pages[page_no - 1]
        shows: list[tuple[str, float, float]] = []

        def visit(text, cm, tm, font_dict, font_size):
            if text and text.strip():
                shows.append((text, float(tm[4]), float(tm[5])))

        try:
            page.extract_text(visitor_text=visit)
        except Exception as exc:
            print(f"page {page_no}: extract error: {exc!r}", file=sys.stderr)
            continue
        if not shows:
            continue

        # Group shows into lines by y-coordinate (within y_tol).
        # Same baseline may be split across many Tj ops with small jitter.
        lines: list[list[tuple[str, float, float]]] = []
        for text, x, y in shows:
            for line in lines:
                if abs(y - line[0][2]) < y_tol:
                    line.append((text, x, y))
                    break
            else:
                lines.append([(text, x, y)])

        # PDF coords: y increases upward, so descending y = top-to-bottom reading.
        lines.sort(key=lambda ln: -ln[0][2])
        for line in lines:
            line.sort(key=lambda s: s[1])
            text = re.sub(r"\s+", " ", " ".join(s[0] for s in line)).strip()
            if not text:
                continue
            text, page_hint = _split_page_number(text)
            if not text:
                continue
            indent = min(s[1] for s in line)
            prefix = _classify_prefix(text)
            out.append(
                TocLine(text=text, page_hint=page_hint, indent=indent, prefix=prefix)
            )
    return out


def _bucket(value: float, size: float) -> int:
    return int(value // size)


# Tiebreaker when indent already matches between two styles. Generic typographic
# convention (parens-doubled is more major than roman, roman than upper letter,
# etc.) — not a book-specific scheme.
_PREFIX_RANK = {
    "paren_double_upper": 0,
    "paren_double_lower": 0,
    "arabic_dotted": 2,
    "arabic": 3,
    "roman": 4,
    "letter_upper": 5,
    "letter_lower": 6,
    "greek_lower": 7,
    "none": 50,
}


def assign_levels(lines: list[TocLine], indent_bucket: float) -> dict[tuple, int]:
    styles: dict[tuple, list[TocLine]] = defaultdict(list)
    for line in lines:
        key = (line.prefix, _bucket(line.indent, indent_bucket))
        styles[key].append(line)
    ordered = sorted(
        styles.keys(),
        key=lambda k: (k[1], _PREFIX_RANK.get(k[0], 50)),
    )
    return {k: i + 1 for i, k in enumerate(ordered)}


def render_outline(
    lines: list[TocLine], levels: dict[tuple, int], indent_bucket: float
) -> str:
    out = [
        "// Draft outline from PDF text-layer TOC via pdf_outline.py.",
        "// Hierarchy from indent + numbering prefix; review by hand.",
        "// Drop prose-summary lines that aren't real headings before add_outline.py.",
        "",
    ]
    for line in lines:
        key = (line.prefix, _bucket(line.indent, indent_bucket))
        level = levels[key]
        hint = f" @ {line.page_hint}" if line.page_hint else ""
        out.append(f"{'#' * level} {line.text}{hint}")
    return "\n".join(out) + "\n"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("input", help="PDF with a text layer (typically already OCR'd)")
    p.add_argument(
        "--toc-pages",
        required=True,
        help="Page range covering the printed TOC, e.g. 25-27 or 25.",
    )
    p.add_argument(
        "--indent-bucket",
        type=float,
        default=8.0,
        help="PDF-user-unit bucket for grouping similar indents. Default 8.",
    )
    p.add_argument(
        "--y-tol",
        type=float,
        default=3.0,
        help="Y-coord tolerance for grouping text-shows into one line. Default 3.",
    )
    args = p.parse_args()

    pages = parse_page_range(args.toc_pages)
    lines = collect_from_text_layer(args.input, pages, args.y_tol)
    if not lines:
        print("No TOC lines found.", file=sys.stderr)
        return 1
    levels = assign_levels(lines, args.indent_bucket)
    print(render_outline(lines, levels, args.indent_bucket))
    return 0


if __name__ == "__main__":
    sys.exit(main())
