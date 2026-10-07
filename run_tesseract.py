#!/usr/bin/env python3
"""Add an invisible, word-aligned OCR text layer to a scanned PDF (local Tesseract).

Free and offline. The result is the same PDF to read, search and highlight in: each
word's invisible text sits over the printed word, so selection lines up with the
glyphs. For Markdown, use pdf_to_markdown.py instead. English only by default.

Usage:
    python run_tesseract.py input.pdf output.pdf
    python run_tesseract.py input.pdf out.pdf --dpi 300 --text-out text.txt
    python run_tesseract.py scan.pdf out.pdf --drop-running-heads   # book pages
    python run_tesseract.py copy.pdf out.pdf --split-spreads        # one book page per page

Photocopies: a sheet holding two book pages is read as two pages, the copier's black
edges and grey shadows are ignored, and tilted pages are read level. The pages keep
their own images; --split-spreads instead writes each book page as a page of its own,
straightened. --no-cleanup reads the pages exactly as they are.

Book pages: footnote reference markers are stripped from the body text, footnotes
stay separate paragraphs, and the running head (title in capitals + page number) is
never glued onto the first paragraph. --drop-running-heads leaves it out entirely.
"""

from __future__ import annotations

import argparse
import shutil
import sys

from ocr.pipeline_tesseract import Settings, run


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", help="Path to the scanned source PDF")
    parser.add_argument("output", help="Path for the OCR'd output PDF")
    parser.add_argument(
        "--lang", default="eng", help="Tesseract language(s). Default 'eng'."
    )
    parser.add_argument("--dpi", type=int, default=300, help="Render resolution (default: 300)")
    parser.add_argument(
        "--min-conf",
        type=float,
        default=0.0,
        help="Drop words below this Tesseract confidence (0-100)",
    )
    parser.add_argument(
        "--font-file", default=None, help="Path to a Unicode TTF for the text layer"
    )
    parser.add_argument(
        "--text-out", default=None, help="Optional path to also dump the plain transcription"
    )
    parser.add_argument(
        "--no-rasterize",
        action="store_true",
        help="Merge onto the original page instead of rebuilding from the rendered image. "
        "Preserves source bytes, but any pre-existing (corrupt) text layer in the source "
        "PDF will remain alongside the OCR layer and contaminate text selection.",
    )
    parser.add_argument(
        "--jpeg-quality",
        type=int,
        default=85,
        help="JPEG quality for the rebuilt page background (default: 85). Ignored with --no-rasterize.",
    )
    parser.add_argument(
        "--drop-running-heads",
        action="store_true",
        help="Leave each page's running head (book/chapter title, page number) out of the "
        "text layer, so copying across a page break gives clean prose.",
    )
    parser.add_argument(
        "--no-cleanup",
        action="store_true",
        help="Read the pages exactly as they are: don't split two-page spreads, ignore "
        "copier shadows or level tilted pages before OCR.",
    )
    parser.add_argument(
        "--split-spreads",
        action="store_true",
        help="Write the two book pages of a photocopied spread as two pages, each "
        "straightened (rebuilds those pages from the image).",
    )
    args = parser.parse_args()
    if args.split_spreads and (args.no_cleanup or args.no_rasterize):
        parser.error("--split-spreads can't be combined with --no-cleanup or --no-rasterize")

    if shutil.which("tesseract") is None:
        print(
            "ERROR: the tesseract binary is not installed.\n"
            "  macOS:         brew install tesseract\n"
            "  Debian/Ubuntu: sudo apt install tesseract-ocr",
            file=sys.stderr,
        )
        return 1

    settings = Settings(
        lang=args.lang,
        dpi=args.dpi,
        min_conf=args.min_conf,
        font_file=args.font_file,
        rasterize=not args.no_rasterize,
        jpeg_quality=args.jpeg_quality,
        drop_running_heads=args.drop_running_heads,
        cleanup=not args.no_cleanup,
        split_spreads=args.split_spreads,
    )
    failures = run(args.input, args.output, settings, text_sidecar=args.text_out)

    if failures:
        print(f"\nDone, but {len(failures)} page(s) failed:", file=sys.stderr)
        for page_no, err in failures:
            print(f"  page {page_no}: {err}", file=sys.stderr)
        return 2
    print(f"\nDone. Wrote {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
