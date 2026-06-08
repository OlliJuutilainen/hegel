#!/usr/bin/env python3
"""Find probable heading lines in an OCR'd PDF by font-size relative to body text.

For each page the script computes the median word height (= body text size) and
prints every line of words whose height is meaningfully larger than that median.
Use it to draft an outline.md when the printed table of contents is too coarse.

Two output modes:

  default: a flat candidate list with relative size per line, in page order — for
    you to eyeball next to your source-language TOC and pick the matching wording.

  --draft-outline: a markdown skeleton with #/##/### levels assigned heuristically
    by relative size, ready to review by hand and pass to add_outline.py.

Typical sizes seen on a scanned academic book:
   ≥ 2.0×   main-chapter level (Preface, Bibliography, ...)
   1.7-2.0× sub-chapter level  (Editor's Introduction, Hegel's Response, ...)
   1.4-1.7× sub-section level  (Search of the Absolute, The Absolute Unmasked, ...)
   1.3×     body-text noise — Tesseract bbox quirks from descenders, italics, etc.

The default threshold of 1.4× filters out the 1.3× body noise while keeping
sub-sections. Lower it (e.g. --threshold 1.3) to catch borderline subsections at
the cost of more noise, raise it (--threshold 1.7) to see only the major levels.

Usage:
    python find_headings.py input_OCR.pdf
    python find_headings.py input_OCR.pdf --pages 10-200 --threshold 1.5
    python find_headings.py input_OCR.pdf --draft-outline > outline.md
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict

from ocr.render import page_count, render_page
from ocr.tesseract_ocr import ocr_words


# Single-word candidate ending in stray punctuation that's usually a footnote
# marker stretching the bbox: 'opinion,!', 'concept.!', 'Being-there?', 'word."',
# 'word.1', 'word.²', etc.  Real one-word headings ('Preface', 'Bibliography',
# 'Introduction') don't carry this trailing junk.
_FOOTNOTE_TAIL = re.compile(
    r"""[a-zA-Z]
        [.,:;]?
        (?:
            ['!?"*‘’“”†‡]+
          | \.\d+
          | \.[!?'"‘’“”]+
        )\s*$""",
    re.VERBOSE,
)


def _looks_like_noise(text: str) -> bool:
    """True if this candidate is probably not a heading.

    Three heuristics, all targeting body text that slipped through because a
    descender, italic, capital, or adjacent footnote marker stretched the bbox:

      1. No 'real' word — none of the tokens contains at least 3 alphabetical
         characters.  Filters single letters ('I', 'a'), tiny Roman numerals
         ('I.', 'II.'), and OCR-garble like 'L AL AR'.
      2. Single-token candidates ending in a stray footnote-marker tail
         ('opinion,!', 'word.1', 'concept."').
      3. Single-token candidates ending in plain sentence punctuation
         ('cognition.', 'singular,', 'philosophy.'). Real one-word headings
         ('Preface', 'Bibliography', 'Index') don't carry trailing punctuation.
    """
    if not text or not text.strip():
        return True
    stripped = text.strip()
    tokens = stripped.split()
    if not any(sum(1 for ch in t if ch.isalpha()) >= 3 for t in tokens):
        return True
    if len(tokens) == 1:
        if _FOOTNOTE_TAIL.search(stripped):
            return True
        if stripped[-1] in ".,;:":
            return True
    return False


def parse_page_range(spec: str | None, total: int) -> list[int]:
    if not spec:
        return list(range(1, total + 1))
    if "-" in spec:
        a, b = spec.split("-", 1)
        return list(range(int(a), int(b) + 1))
    return [int(spec)]


def collect_candidates(
    pdf_path: str,
    pages: list[int],
    threshold: float,
    min_words: int,
    lang: str,
    dpi: int,
    on_candidate=None,
    progress=True,
    filter_noise=True,
) -> list[tuple[int, float, str]]:
    """Return [(page_number, rel_size, text), ...] in page+reading order.

    `on_candidate(page, rel, text)` is called for each candidate as it's found —
    so the caller can print/flush in real time instead of waiting for the full
    pass to finish. `progress=True` prints a per-page progress line to stderr.
    """
    candidates: list[tuple[int, float, str]] = []
    total = len(pages)
    for i, page_no in enumerate(pages, 1):
        if progress:
            print(
                f"\r  page {page_no} ({i}/{total})…",
                end="",
                file=sys.stderr,
                flush=True,
            )
        try:
            image = render_page(pdf_path, page_no, dpi)
            words = ocr_words(image, lang=lang)
        except Exception as exc:
            print(f"\n# page {page_no}: render/ocr error: {exc!r}", file=sys.stderr)
            continue
        if not words:
            continue
        heights = sorted(w.height for w in words)
        median = heights[len(heights) // 2]
        if median <= 0:
            continue
        large = [w for w in words if w.height >= threshold * median]
        if not large:
            continue
        by_line: dict[tuple, list] = defaultdict(list)
        for w in large:
            by_line[(w.block_num, w.par_num, w.line_num)].append(w)
        for key in sorted(by_line.keys()):
            line_words = sorted(by_line[key], key=lambda w: (w.word_num, w.left))
            if len(line_words) < min_words:
                continue
            text = " ".join(w.text for w in line_words)
            if filter_noise and _looks_like_noise(text):
                continue
            rel = max(w.height for w in line_words) / median
            candidates.append((page_no, rel, text))
            if on_candidate is not None:
                on_candidate(page_no, rel, text)
    if progress:
        print(f"\r  done: scanned {total} page(s).", file=sys.stderr, flush=True)
    return candidates


def render_draft_outline(candidates: list[tuple[int, float, str]]) -> str:
    """Render candidates as a markdown outline.md draft.

    Level mapping is heuristic and fixed; review carefully before using:
        # if rel >= 2.0×   (main chapters)
        ## if 1.7 ≤ rel < 2.0   (sub-chapters)
        ### otherwise   (sub-sections)
    """
    lines = [
        "// Draft outline generated by find_headings.py --draft-outline.",
        "// Heuristic level mapping by relative font size:",
        "//   # for >= 2.0×,  ## for 1.7-2.0×,  ### for 1.4-1.7×",
        "// Expect false positives, missing real headings, and miscategorized levels.",
        "// Review/adjust by hand before passing to add_outline.py.",
        "",
    ]
    for page, rel, text in candidates:
        level = "#" if rel >= 2.0 else "##" if rel >= 1.7 else "###"
        lines.append(f"{level} {text} @ {page}")
    return "\n".join(lines)


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
        default=1.4,
        help="Words counted as 'heading' have height >= threshold × page median. "
        "Default 1.4 (filters out body-text bbox noise while keeping sub-sections).",
    )
    parser.add_argument(
        "--min-words",
        type=int,
        default=1,
        help="Skip lines with fewer than this many large words (filters single-glyph noise).",
    )
    parser.add_argument("--lang", default="eng", help="Tesseract language. Default eng.")
    parser.add_argument("--dpi", type=int, default=300, help="Render DPI. Default 300.")
    parser.add_argument(
        "--draft-outline",
        action="store_true",
        help="Print a markdown outline draft instead of the flat candidate list.",
    )
    parser.add_argument(
        "--keep-noise",
        action="store_true",
        help="Disable the noise filter that drops single-letter lines and body "
        "words inflated by adjacent footnote markers.",
    )
    args = parser.parse_args()

    total = page_count(args.input)
    pages = parse_page_range(args.pages, total)

    if args.draft_outline:
        # Draft mode needs the full list before deciding heading levels.
        candidates = collect_candidates(
            args.input,
            pages,
            args.threshold,
            args.min_words,
            args.lang,
            args.dpi,
            filter_noise=not args.keep_noise,
        )
        print(render_draft_outline(candidates))
    else:
        # Default mode: stream each candidate to stdout as it's found, with flush,
        # so the user sees progress in the redirected file in real time.
        print(f"# Heading candidates in {args.input}")
        print(f"# Threshold: word height >= {args.threshold}× page median")
        print(f"# Columns: PAGE   REL_SIZE   TEXT")
        print(flush=True)

        def emit(page: int, rel: float, text: str) -> None:
            print(f"  {page:>4}   {rel:>4.1f}×   {text}", flush=True)

        collect_candidates(
            args.input,
            pages,
            args.threshold,
            args.min_words,
            args.lang,
            args.dpi,
            on_candidate=emit,
            filter_noise=not args.keep_noise,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
