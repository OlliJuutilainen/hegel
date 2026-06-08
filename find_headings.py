#!/usr/bin/env python3
"""Find probable heading lines in an OCR'd PDF by font-size relative to body text.

For each page the script computes the median word height (= body text size) and
prints every line of words whose height is meaningfully larger than that median.
The output gives you, per page, the candidate headings with their relative size
multiplier — a quick scan replaces the brain-numbing job of hunting headings by
hand through a several-hundred-page book.

Use it to draft your outline.md against Inwood/Pinkard/etc. when the printed
table of contents only has a few coarse levels but you want a detailed outline.

Usage:
    python find_headings.py input_OCR.pdf
    python find_headings.py input_OCR.pdf --pages 10-50 --threshold 1.3

Each output line:
    PAGE  REL_SIZE  TEXT
where REL_SIZE is the largest word's height on that line divided by the page's
median word height. 1.5× and up are almost always real headings; 1.2-1.5× tends
to mix real sub-headings, emphasized words, and OCR noise — eyeball them.
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict

from ocr.render import page_count, render_page
from ocr.tesseract_ocr import ocr_words


def parse_page_range(spec: str | None, total: int) -> list[int]:
    if not spec:
        return list(range(1, total + 1))
    if "-" in spec:
        a, b = spec.split("-", 1)
        return list(range(int(a), int(b) + 1))
    return [int(spec)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", help="Path to the OCR'd PDF")
    parser.add_argument(
        "--pages",
        default=None,
        help="Page range to scan, e.g. 10-50 or just 17. Default: all pages.",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=1.25,
        help="Words counted as 'heading' have height >= threshold × page median. Default 1.25.",
    )
    parser.add_argument(
        "--min-words",
        type=int,
        default=1,
        help="Skip lines with fewer than this many large words (filters single-glyph noise).",
    )
    parser.add_argument("--lang", default="eng", help="Tesseract language. Default eng.")
    parser.add_argument("--dpi", type=int, default=300, help="Render DPI. Default 300.")
    args = parser.parse_args()

    total = page_count(args.input)
    pages = parse_page_range(args.pages, total)

    print(f"# Heading candidates in {args.input}")
    print(f"# Threshold: word height >= {args.threshold}× page median")
    print(f"# Columns: PAGE   REL_SIZE   TEXT")
    print()

    for page_no in pages:
        try:
            image = render_page(args.input, page_no, args.dpi)
            words = ocr_words(image, lang=args.lang)
        except Exception as exc:
            print(f"# page {page_no}: render/ocr error: {exc!r}", file=sys.stderr)
            continue
        if not words:
            continue

        heights = sorted(w.height for w in words)
        median = heights[len(heights) // 2]
        if median <= 0:
            continue

        large = [w for w in words if w.height >= args.threshold * median]
        if not large:
            continue

        by_line: dict[tuple, list] = defaultdict(list)
        for w in large:
            by_line[(w.block_num, w.par_num, w.line_num)].append(w)

        for key in sorted(by_line.keys()):
            line_words = sorted(by_line[key], key=lambda w: (w.word_num, w.left))
            if len(line_words) < args.min_words:
                continue
            text = " ".join(w.text for w in line_words)
            rel = max(w.height for w in line_words) / median
            print(f"  {page_no:>4}   {rel:>4.1f}×   {text}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
