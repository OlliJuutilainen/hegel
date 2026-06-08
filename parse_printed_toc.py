#!/usr/bin/env python3
"""Build an outline.md draft from a book's printed table-of-contents pages.

Given an OCR'd PDF and a page range pointing at its printed TOC, this script
extracts the TOC entries and infers their hierarchy from a combination of:

  - indentation        (lines flush-left rank above deeply indented ones)
  - numbering prefix   (paren-doubled '(AA.)', roman 'I.', uppercase 'A.',
                        lowercase 'a.', greek 'α.', arabic '1.' or '1.1')
  - font size          (bigger relative height ranks above smaller, when
                        indents and prefixes don't discriminate)

Nothing is hardcoded to a particular book's scheme. The script clusters the
TOC's actual rendered styles — (prefix_class, indent_bucket, size_bucket) —
and orders them by signal strength: bigger size > smaller indent > more major
prefix class. A TOC where every line is flush-left and uniformly sized but
distinguished by prefix only (rare) still works; one that uses indent only
(no numbering) also works.

Roman-numeral OCR errors are corrected before classification: Tesseract
systematically reads I. → L., II. → IL., III. → I11., VI. → VL.,
VII. → VIL., VIII. → VIIL. — all of these map back.

Usage:
    python parse_printed_toc.py Inwood_OCR.pdf --toc-pages 7-9 > outline_draft.md
    python parse_printed_toc.py Inwood_OCR.pdf --toc-pages 7 --dpi 200
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from dataclasses import dataclass

from ocr.render import render_page
from ocr.tesseract_ocr import ocr_words


# Tesseract systematically misreads several roman numerals as look-alikes.
# Applied as a first-token fixup before prefix classification.
_ROMAN_FIXUPS = [
    (re.compile(r"^VIIL(?=\.)"), "VIII"),
    (re.compile(r"^VIL(?=\.)"), "VII"),
    (re.compile(r"^VL(?=\.)"), "VI"),
    (re.compile(r"^I11(?=\.)"), "III"),
    (re.compile(r"^IL(?=\.)"), "II"),
    (re.compile(r"^LL(?=\.)"), "II"),
    (re.compile(r"^L(?=\.)"), "I"),
]


def _fix_roman_prefix(text: str) -> str:
    for pat, sub in _ROMAN_FIXUPS:
        new = pat.sub(sub, text, count=1)
        if new != text:
            return new
    return text


# Numbering prefix classification. Tested top to bottom; first match wins.
# Classes are content-agnostic shape labels — we don't hardcode their level.
_PREFIX_PATTERNS = [
    ("paren_double_upper", re.compile(r"^\(([A-Z])\1\.\)")),
    ("paren_double_lower", re.compile(r"^\(([a-z])\1\.\)")),
    ("arabic_dotted", re.compile(r"^\d+\.\d+(?:\.\d+)*(?:\s|$)")),
    ("arabic", re.compile(r"^\d+\.(?:\s|$)")),
    ("roman", re.compile(r"^[IVX]+\.(?:\s|$)")),
    ("letter_upper", re.compile(r"^[A-Z]\.(?:\s|$)")),
    ("letter_lower", re.compile(r"^[a-z]\.(?:\s|$)")),
    ("greek_lower", re.compile(r"^[αβγδεζηθικ]\.(?:\s|$)")),
]


def _classify_prefix(text: str) -> str:
    for name, pat in _PREFIX_PATTERNS:
        if pat.match(text):
            return name
    return "none"


# Page number at end of TOC line — usual forms: "title 27", "title . 27",
# "title.....27".  Returns the cleaned text and the integer, if any.
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
    indent: int
    height: int
    prefix: str


def parse_page_range(spec: str) -> list[int]:
    if "-" in spec:
        a, b = spec.split("-", 1)
        return list(range(int(a), int(b) + 1))
    return [int(spec)]


def collect_toc_lines(
    pdf_path: str, pages: list[int], dpi: int, lang: str
) -> list[TocLine]:
    out: list[TocLine] = []
    for page_no in pages:
        print(f"  page {page_no}…", file=sys.stderr, flush=True)
        image = render_page(pdf_path, page_no, dpi)
        words = ocr_words(image, lang=lang)
        if not words:
            continue
        by_line: dict[tuple, list] = defaultdict(list)
        for w in words:
            by_line[(w.block_num, w.par_num, w.line_num)].append(w)
        for key in sorted(by_line.keys()):
            line_words = sorted(by_line[key], key=lambda w: (w.word_num, w.left))
            text = " ".join(w.text for w in line_words).strip()
            if not text:
                continue
            text = _fix_roman_prefix(text)
            text, page_hint = _split_page_number(text)
            if not text:
                continue
            indent = min(w.left for w in line_words)
            height = max(w.height for w in line_words)
            prefix = _classify_prefix(text)
            out.append(
                TocLine(
                    text=text,
                    page_hint=page_hint,
                    indent=indent,
                    height=height,
                    prefix=prefix,
                )
            )
    return out


def _bucket(value: int, size: int) -> int:
    return (value // size) * size


# Tiebreaker when indent and size already match for two styles — paren-doubled
# is more major than roman, roman than uppercase letter, etc. This is a
# generic typographic convention, not a book-specific scheme.
_PREFIX_RANK = {
    "paren_double_upper": 0,
    "paren_double_lower": 0,  # same shape, just case — treat as equal level
    "arabic_dotted": 2,
    "arabic": 3,
    "roman": 4,
    "letter_upper": 5,
    "letter_lower": 6,
    "greek_lower": 7,
    "none": 50,
}


def assign_levels(
    lines: list[TocLine], indent_bucket: int, height_bucket: int
) -> dict[tuple, int]:
    """Cluster lines by (prefix, indent_bucket, height_bucket) and rank styles.

    Returns a mapping from style key to nesting level (1 = topmost). Order is:
      1. Height descending  — taller text ranks higher.
      2. Indent ascending   — flusher-left text ranks higher.
      3. Prefix rank        — paren_double > arabic > roman > upper > lower > greek > none.
    Styles that are identical on all three signals collapse into the same level.
    """
    styles: dict[tuple, list[TocLine]] = defaultdict(list)
    for line in lines:
        key = (
            line.prefix,
            _bucket(line.indent, indent_bucket),
            _bucket(line.height, height_bucket),
        )
        styles[key].append(line)
    ordered = sorted(
        styles.keys(),
        key=lambda k: (-k[2], k[1], _PREFIX_RANK.get(k[0], 50)),
    )
    return {k: i + 1 for i, k in enumerate(ordered)}


def render_outline(
    lines: list[TocLine],
    levels: dict[tuple, int],
    indent_bucket: int,
    height_bucket: int,
) -> str:
    out = [
        "// Draft outline from printed-TOC scan via parse_printed_toc.py.",
        "// Hierarchy inferred from font size + indent + numbering prefix.",
        "// Expect some misclassifications; review by hand before add_outline.py.",
        "",
    ]
    for line in lines:
        key = (
            line.prefix,
            _bucket(line.indent, indent_bucket),
            _bucket(line.height, height_bucket),
        )
        level = levels[key]
        hint = f" @ {line.page_hint}" if line.page_hint else ""
        out.append(f"{'#' * level} {line.text}{hint}")
    return "\n".join(out)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("input", help="Path to the OCR'd PDF")
    p.add_argument(
        "--toc-pages",
        required=True,
        help="Page range covering the printed TOC, e.g. 7-9 or 7.",
    )
    p.add_argument("--dpi", type=int, default=300, help="Render DPI. Default 300.")
    p.add_argument("--lang", default="eng", help="Tesseract language. Default eng.")
    p.add_argument(
        "--indent-bucket",
        type=int,
        default=30,
        help="Pixel bucket size for grouping similar indents. Default 30.",
    )
    p.add_argument(
        "--height-bucket",
        type=int,
        default=6,
        help="Pixel bucket size for grouping similar font heights. Default 6.",
    )
    args = p.parse_args()

    pages = parse_page_range(args.toc_pages)
    lines = collect_toc_lines(args.input, pages, args.dpi, args.lang)
    if not lines:
        print("No TOC lines found.", file=sys.stderr)
        return 1
    levels = assign_levels(lines, args.indent_bucket, args.height_bucket)
    print(render_outline(lines, levels, args.indent_bucket, args.height_bucket))
    return 0


if __name__ == "__main__":
    sys.exit(main())
