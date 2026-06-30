#!/usr/bin/env python3
"""Route 2: local Tesseract OCR that adds a word-aligned invisible text layer.

Free and offline. Uses Tesseract's per-word bounding boxes to position the
invisible text so highlighting/selection lines up with the printed glyphs, and
leaves the original page images untouched. English only by default.

Usage:
    python run_tesseract.py input.pdf output.pdf
    python run_tesseract.py input.pdf out.pdf --dpi 300 --text-out text.txt
"""

from __future__ import annotations

import argparse
import os
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
        "--text-out",
        default=None,
        help="Path for the plain-text transcription. Default: the output PDF's name "
        "with a .txt extension. Use --no-text-out to skip it.",
    )
    parser.add_argument(
        "--no-text-out",
        action="store_true",
        help="Don't write the plain-text transcription sidecar.",
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
        "--drop-margin-refs",
        action="store_true",
        help="Drop Akademie-Ausgabe-style margin references like '[4:408]' from the "
        "text layer so they aren't copied with selected body text. The page image "
        "still shows them.",
    )
    parser.add_argument(
        "--psm",
        type=int,
        default=None,
        help="Tesseract page segmentation mode. Default (3) does full layout "
        "analysis but can drop a line between auto-detected blocks on a "
        "single-column page. Try 4 (single column, variable sizes) or 6 (single "
        "uniform block) for plain book pages.",
    )
    args = parser.parse_args()

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
        drop_margin_refs=args.drop_margin_refs,
        psm=args.psm,
    )
    # Plain-text sidecar is written by default (next to the output PDF) unless
    # suppressed; --text-out overrides its location.
    if args.no_text_out:
        text_sidecar = None
    elif args.text_out:
        text_sidecar = args.text_out
    else:
        text_sidecar = os.path.splitext(args.output)[0] + ".txt"

    failures = run(args.input, args.output, settings, text_sidecar=text_sidecar)

    if failures:
        print(f"\nDone, but {len(failures)} page(s) failed:", file=sys.stderr)
        for page_no, err in failures:
            print(f"  page {page_no}: {err}", file=sys.stderr)
        return 2
    print(f"\nDone. Wrote {args.output}")
    if text_sidecar is not None:
        print(f"Plain text: {text_sidecar}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
