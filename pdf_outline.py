#!/usr/bin/env python3
"""Build outline.md draft from the printed TOC pages of a text-layered PDF.

Reads the printed table-of-contents straight from the PDF's existing text
layer (via pypdf's text-show visitor) instead of rasterizing + OCRing —
faster and typographically cleaner.

Hierarchy is driven by INDENTATION, not by the numbering prefix. In a
printed TOC the visual left margin is the authoritative signal of nesting
depth: Hegel's contents page puts 'A. Consciousness', '(BB.) Spirit' and
'Preface' all at the same flush-left margin (= top level) even though their
prefixes differ wildly, while 'A. Observing reason' sits indented under
'V.' as a sub-sub-entry. So we cluster lines by indent and rank the
clusters left-to-right; each indent cluster is one '#' level. Nothing is
hardcoded to a particular book.

The numbering prefix is still used for two things: dropping prose-summary
lines (which carry no prefix and are long / full of page refs), and
cleaning up roman numerals the OCR mangled in the title text ('VL.' -> 'VI.').

Use this when your PDF already has a text layer and its printed TOC carries
more detail than the EPUB nav (lettered subsections, greek subsubsections).

Usage:
    python pdf_outline.py inwood2.pdf --toc-pages 25-27 > outline.md
    python pdf_outline.py inwood2.pdf --toc-pages 25-27 --indent-gap 6
    python pdf_outline.py inwood2.pdf --toc-pages 25-27 --keep-prose
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass

from pypdf import PdfReader


# Tesseract systematically mangles roman numerals in the text layer; normalize
# the leading token (with or without the trailing dot the OCR sometimes drops)
# so the title reads cleanly. Longest patterns first. We do NOT touch a bare
# '1.' (ambiguous with arabic) — only the L-contaminated forms.
_ROMAN_FIXUPS = [
    (re.compile(r"^VIIL\.?\s*"), "VIII. "),
    (re.compile(r"^VIL\.?\s*"), "VII. "),
    (re.compile(r"^VL\.?\s*"), "VI. "),
    (re.compile(r"^I11\.?\s*"), "III. "),
    (re.compile(r"^II1\.?\s*"), "III. "),
    (re.compile(r"^IL\.?\s*"), "II. "),
    (re.compile(r"^L\.\s*"), "I. "),
]


def _fix_roman_prefix(text: str) -> str:
    for pat, sub in _ROMAN_FIXUPS:
        new = pat.sub(sub, text, count=1)
        if new != text:
            return new
    return text


# Numbering-prefix classification — used only for prose detection, not leveling.
# Trailing space/dot not required (OCR drops it: 'A.Independence', 'VIL Religion').
_PREFIX_PATTERNS = [
    ("paren_double_upper", re.compile(r"^\(([A-Z])\1\.\)")),
    ("paren_double_lower", re.compile(r"^\(([a-z])\1\.\)")),
    ("arabic_dotted",      re.compile(r"^\d+\.\d+")),
    ("arabic",             re.compile(r"^\d+\.")),
    ("roman",              re.compile(r"^[IVX]+\.")),
    ("letter_upper",       re.compile(r"^[A-Z]\.")),
    ("letter_lower",       re.compile(r"^[a-z]\.")),
    ("greek_lower",        re.compile(r"^[αβγδεζηθικ]\.")),
]


def _classify_prefix(text: str) -> str:
    for name, pat in _PREFIX_PATTERNS:
        if pat.match(text):
            return name
    return "none"


# A trailing page number on a TOC line ('Sensory Certainty 27', 'title ... 27').
_PAGE_NUMBER_RE = re.compile(r"\s+\.{0,}\s*(\d{1,4})\s*$")
# Inline parenthesized page refs scattered through a prose summary ('(8)', '(33)').
_PAGE_REF_RE = re.compile(r"\(\d+\)")


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


def _is_prose(line: TocLine, min_words: int) -> bool:
    """Prefix-less summary text rather than a heading.

    Real prefix-less headings ('Preface', 'Introduction', short chapter titles)
    are kept; long prose or anything sprinkled with parenthesized page refs is
    dropped. Numbered headings (any prefix) are never treated as prose.
    """
    if line.prefix != "none":
        return False
    if _PAGE_REF_RE.search(line.text):
        return True
    return len(line.text.split()) >= min_words


def _is_toc_title(line: TocLine) -> bool:
    return line.text.strip().lower() in {"contents", "table of contents"}


def parse_page_range(spec: str) -> list[int]:
    if "-" in spec:
        a, b = spec.split("-", 1)
        return list(range(int(a), int(b) + 1))
    return [int(spec)]


def collect_from_text_layer(pdf_path: str, pages: list[int], y_tol: float) -> list[TocLine]:
    """Read TOC pages from the PDF text layer; group shows into lines."""
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

        # Group shows into lines by shared baseline y (within y_tol).
        lines: list[list[tuple[str, float, float]]] = []
        for text, x, y in shows:
            for line in lines:
                if abs(y - line[0][2]) < y_tol:
                    line.append((text, x, y))
                    break
            else:
                lines.append([(text, x, y)])

        # PDF y increases upward; descending y = top-to-bottom reading order.
        lines.sort(key=lambda ln: -ln[0][2])
        for line in lines:
            line.sort(key=lambda s: s[1])
            text = re.sub(r"\s+", " ", " ".join(s[0] for s in line)).strip()
            if not text:
                continue
            text, page_hint = _split_page_number(text)
            text = _fix_roman_prefix(text)
            if not text:
                continue
            indent = min(s[1] for s in line)
            out.append(
                TocLine(
                    text=text,
                    page_hint=page_hint,
                    indent=indent,
                    prefix=_classify_prefix(text),
                )
            )
    return out


def assign_levels(lines: list[TocLine], indent_gap: float) -> dict[float, int]:
    """Cluster the distinct indents agglomeratively and rank them left-to-right.

    Each cluster (a group of indents no more than `indent_gap` apart) is one
    nesting level. Small jitter within a level collapses; the clear horizontal
    gap between levels separates them. Returns {rounded_indent: level}.
    """
    uniq = sorted({round(l.indent, 1) for l in lines})
    mapping: dict[float, int] = {}
    level = 0
    prev: float | None = None
    for x in uniq:
        if prev is None or (x - prev) > indent_gap:
            level += 1
        mapping[x] = level
        prev = x
    return mapping


def _level_of(line: TocLine, mapping: dict[float, int]) -> int:
    return mapping[round(line.indent, 1)]


def render_outline(lines: list[TocLine], mapping: dict[float, int]) -> str:
    out = [
        "// Draft outline from PDF text-layer TOC via pdf_outline.py.",
        "// Levels come from indentation depth; review by hand before add_outline.py.",
        "",
    ]
    for line in lines:
        level = _level_of(line, mapping)
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
        "--indent-gap",
        type=float,
        default=6.0,
        help="Min horizontal gap (PDF units) that separates two nesting levels. "
        "Raise if distinct levels get merged, lower if one level splits. Default 6.",
    )
    p.add_argument(
        "--y-tol",
        type=float,
        default=3.0,
        help="Y-coord tolerance for grouping text-shows into one line. Default 3.",
    )
    p.add_argument(
        "--prose-min-words",
        type=int,
        default=10,
        help="Prefix-less lines with at least this many words are treated as "
        "prose summaries and dropped. Default 10.",
    )
    p.add_argument(
        "--keep-prose",
        action="store_true",
        help="Disable prose-summary filtering (keep every line).",
    )
    args = p.parse_args()

    pages = parse_page_range(args.toc_pages)
    lines = collect_from_text_layer(args.input, pages, args.y_tol)
    lines = [l for l in lines if not _is_toc_title(l)]
    if not args.keep_prose:
        lines = [l for l in lines if not _is_prose(l, args.prose_min_words)]
    if not lines:
        print("No TOC lines found.", file=sys.stderr)
        return 1
    mapping = assign_levels(lines, args.indent_gap)
    print(render_outline(lines, mapping))
    return 0


if __name__ == "__main__":
    sys.exit(main())
