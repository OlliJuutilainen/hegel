#!/usr/bin/env python3
"""Dump Tesseract paragraph structure for diagnosis.

Finds the page containing a given needle string ('From the outset' by default —
the over-split paragraph in the Henrich preface) and prints every word's text,
block_num, par_num, line_num, top, left, and height. Lets us see what Tesseract
actually returns so we can understand why _merge_continuation_paragraphs misses.
"""

from __future__ import annotations

import sys

from ocr.render import page_count, render_page
from ocr.tesseract_ocr import ocr_words


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: python diag.py <input.pdf> [needle='From the outset']", file=sys.stderr)
        return 1
    pdf = sys.argv[1]
    needle = sys.argv[2] if len(sys.argv) > 2 else "From the outset"
    total = page_count(pdf)

    target = None
    for p in range(1, min(30, total + 1)):
        img = render_page(pdf, p, 300)
        words = ocr_words(img, lang="eng")
        joined = " ".join(w.text for w in words)
        if needle.lower() in joined.lower():
            target = p
            break
    if target is None:
        print(f"needle {needle!r} not found in the first 30 pages", file=sys.stderr)
        return 2

    print(f"# Found needle on page {target}\n")
    img = render_page(pdf, target, 300)
    words = ocr_words(img, lang="eng")
    needle_first = needle.split()[0]
    start = next((i for i, w in enumerate(words) if w.text == needle_first), 0)

    print(f"{'block':>5} {'par':>3} {'line':>4} {'top':>5} {'left':>5} {'h':>3}  text")
    print("-" * 60)
    for w in words[start : start + 100]:
        print(
            f"{w.block_num:>5} {w.par_num:>3} {w.line_num:>4} "
            f"{w.top:>5} {w.left:>5} {w.height:>3}  {w.text}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
