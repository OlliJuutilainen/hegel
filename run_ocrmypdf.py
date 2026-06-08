#!/usr/bin/env python3
"""Route 1: re-OCR a scanned PDF with OCRmyPDF (Tesseract), English only.

Two modes:
  default (--redo-ocr): replace the existing (corrupt) text layer with a clean,
      word-aligned one while leaving the original page images 100% untouched.
  --force (--force-ocr): rasterize each page and deskew/clean it before OCR.
      Use this for poor scans where cleaning improves recognition. It changes
      the page images, so it is not byte-identical to the original.

English only (`-l eng`) by default: adding languages can degrade English
accuracy, and English is the priority.

Note: --deskew/--clean alter the image and are therefore only valid in --force
mode; OCRmyPDF rejects them together with --redo-ocr.

Usage:
    python run_ocrmypdf.py input.pdf output.pdf
    python run_ocrmypdf.py input.pdf out.pdf --pages 10-15        # cheap test slice
    python run_ocrmypdf.py input.pdf out.pdf --force --no-clean   # rasterize, deskew only
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", help="Path to the scanned source PDF")
    parser.add_argument("output", help="Path for the OCR'd output PDF")
    parser.add_argument(
        "--lang",
        default="eng",
        help="Tesseract language(s). Default 'eng' (strongest English accuracy).",
    )
    parser.add_argument("--pages", default=None, help="Limit to a page range, e.g. 10-15")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Rasterize + deskew/clean before OCR (changes the images)",
    )
    parser.add_argument(
        "--no-deskew", action="store_true", help="In --force mode, skip --deskew"
    )
    parser.add_argument(
        "--no-clean", action="store_true", help="In --force mode, skip --clean"
    )
    args, passthrough = parser.parse_known_args()

    if shutil.which("ocrmypdf") is None:
        print(
            "ERROR: ocrmypdf is not installed.\n"
            "  macOS:         brew install ocrmypdf tesseract unpaper\n"
            "  Debian/Ubuntu: sudo apt install ocrmypdf tesseract-ocr ghostscript unpaper",
            file=sys.stderr,
        )
        return 1

    if args.force:
        cmd = ["ocrmypdf", "--force-ocr", "-l", args.lang]
        if not args.no_deskew:
            cmd.append("--deskew")
        if not args.no_clean:
            cmd.append("--clean")
    else:
        # --redo-ocr preserves the original images, so it cannot also deskew/clean.
        cmd = ["ocrmypdf", "--redo-ocr", "-l", args.lang]

    if args.pages:
        cmd += ["--pages", args.pages]
    cmd += passthrough
    cmd += [args.input, args.output]

    print("Running:", " ".join(cmd))
    return subprocess.run(cmd).returncode


if __name__ == "__main__":
    sys.exit(main())
