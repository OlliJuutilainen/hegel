#!/usr/bin/env python3
"""Add a navigable outline (table of contents) to an OCR'd PDF based on a markdown-style file.

For each entry in the TOC file the script searches the PDF's text layer for the heading
string and creates an outline item pointing to the *actual location of that heading on
the page* (specific Y-coordinate), not just the page itself.

TOC file format (markdown-ish):

    # Preface
    # Introduction
    ## Henrich and Hegel
    ## The Speculative Self
    # Chapter 1: Foo @ 17
    ## 1.1 Bar
    # Bibliography

`# ` = top-level entry, `## ` = sub-entry, `### ` = sub-sub-entry, etc. The optional
`@ N` suffix is a 1-based page hint that lets you disambiguate when the heading also
appears in the book's own table-of-contents pages — the script will then prefer the
occurrence at or after page N.

Without a hint, the script searches forward from where the previous TOC entry was
found, so listing entries in reading order usually picks the right occurrences
naturally. If a heading still resolves to the wrong place, add an `@ N` hint.

Usage:
    python add_outline.py outline.md input_OCR.pdf input_OCR_outlined.pdf
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass

from pypdf import PdfReader, PdfWriter
from pypdf.generic import Fit


@dataclass
class TocEntry:
    title: str
    level: int  # 1-based: 1 = '#', 2 = '##', etc.
    page_hint: int | None = None  # 1-based page hint
    found_page: int | None = None  # 0-based page index
    found_y: float | None = None


_ENTRY_RE = re.compile(r"^(#+)\s+(.+?)(?:\s+@\s+(\d+))?\s*$")


def parse_toc(text: str) -> list[TocEntry]:
    """Parse markdown-style TOC text into a flat list of entries (level kept on each)."""
    entries: list[TocEntry] = []
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("//"):
            continue
        m = _ENTRY_RE.match(line.rstrip())
        if not m:
            continue
        entries.append(
            TocEntry(
                title=m.group(2).strip(),
                level=len(m.group(1)),
                page_hint=int(m.group(3)) if m.group(3) else None,
            )
        )
    return entries


def _normalize(s: str) -> str:
    """Lowercase, collapse whitespace — for fuzzy heading matching."""
    return re.sub(r"\s+", " ", s.strip().lower())


def _page_text_shows(page) -> list[tuple[str, float, float]]:
    """Return [(text, x, y), ...] for every Tj/TJ in this page, in stream order.

    pypdf's extract_text visitor gives us the text and the active text matrix at the
    moment of the operator, so tm[4]/tm[5] are the show's translation in user space.
    """
    shows: list[tuple[str, float, float]] = []

    def visit(text, cm, tm, font_dict, font_size):
        if text and text.strip():
            shows.append((text, float(tm[4]), float(tm[5])))

    try:
        page.extract_text(visitor_text=visit)
    except Exception:
        pass
    return shows


def find_heading(reader: PdfReader, heading: str, start_page: int = 0):
    """Find the first occurrence of `heading` at or after `start_page`.

    Returns (page_index, y) of the text show that *begins* the heading string —
    i.e. the position whose Tj starts the match, not just any Tj whose forward
    concatenation contains the heading. This matters when the heading is preceded
    on the same page by another heading whose first word collides with text earlier.
    """
    needle = _normalize(heading)
    if not needle:
        return None
    for page_idx in range(start_page, len(reader.pages)):
        shows = _page_text_shows(reader.pages[page_idx])
        for i in range(len(shows)):
            accumulated = shows[i][0]
            j = i
            # Pull in following shows until we have enough characters to match `needle`
            while (
                len(_normalize(accumulated)) < len(needle)
                and j + 1 < min(i + 20, len(shows))
            ):
                j += 1
                accumulated = accumulated + " " + shows[j][0]
            norm = _normalize(accumulated)
            pos = norm.find(needle)
            # Match must begin at or very near the start of this show
            # (small slack absorbs stray leading punctuation or a stray space)
            if 0 <= pos <= 2:
                return page_idx, shows[i][2]
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("toc", help="Path to the markdown-style TOC file")
    parser.add_argument("input", help="Input PDF (typically the OCR'd one)")
    parser.add_argument("output", help="Output PDF with outline added")
    args = parser.parse_args()

    with open(args.toc, encoding="utf-8") as handle:
        entries = parse_toc(handle.read())
    if not entries:
        print(f"WARNING: no TOC entries parsed from {args.toc}", file=sys.stderr)
        return 1

    reader = PdfReader(args.input)
    writer = PdfWriter()
    writer.append_pages_from_reader(reader)

    parent_stack: list[tuple[int, object | None]] = [(0, None)]
    cursor_page = 0
    found = 0
    missing: list[str] = []

    for entry in entries:
        # Search forward from the cursor, unless the user gave a page hint.
        start = (entry.page_hint - 1) if entry.page_hint else cursor_page
        start = max(0, min(start, len(reader.pages) - 1))
        result = find_heading(reader, entry.title, start_page=start)
        # If the hint missed, sweep the whole PDF as a fallback.
        if result is None and entry.page_hint is not None:
            result = find_heading(reader, entry.title, start_page=0)
        if result is None:
            missing.append(entry.title)
            continue

        page_idx, y = result
        entry.found_page = page_idx
        entry.found_y = y
        cursor_page = page_idx

        while parent_stack and parent_stack[-1][0] >= entry.level:
            parent_stack.pop()
        parent = parent_stack[-1][1]
        ref = writer.add_outline_item(
            entry.title, page_idx, parent=parent, fit=Fit.xyz(top=y)
        )
        parent_stack.append((entry.level, ref))
        found += 1

    with open(args.output, "wb") as handle:
        writer.write(handle)

    print(f"Added {found}/{len(entries)} outline entries to {args.output}")
    if missing:
        print(
            "Could not locate the following heading(s) — check spelling, "
            "or add an '@ N' page hint to disambiguate:",
            file=sys.stderr,
        )
        for title in missing:
            print(f"  - {title!r}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
