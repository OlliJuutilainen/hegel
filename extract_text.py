#!/usr/bin/env python3
"""Dump a clean plain-text transcription from an already-OCR'd PDF — no re-OCR.

run_tesseract.py embeds a clean, de-hyphenated, paragraph-flowing copy of each
paragraph in the invisible layer's /ActualText spans. This pulls that text back
out of an existing output PDF, so you can get the whole book as .txt instantly
without running OCR again.

For pages that carry no /ActualText (e.g. an inserted photo page, or a PDF made
by another tool), it falls back to pypdf's positional text extraction.

Usage:
    python extract_text.py nimike-ocr.pdf            # -> nimike-ocr.txt
    python extract_text.py nimike-ocr.pdf book.txt
    python extract_text.py nimike-ocr.pdf -          # write to stdout
"""

from __future__ import annotations

import argparse
import os
import re
import sys

from pypdf import PdfReader

# /ActualText <FEFF...UTF-16BE-hex...> as written by overlay._actualtext_hex.
_ACTUAL_TEXT = re.compile(rb"/ActualText\s*<([0-9A-Fa-f]+)>")


def _decode_hex(hex_bytes: bytes) -> str:
    try:
        raw = bytes.fromhex(hex_bytes.decode("ascii"))
        return raw.decode("utf-16-be").replace("﻿", "").strip()
    except Exception:
        return ""


def page_text(page) -> str:
    """Clean text for one page: prefer embedded /ActualText, fall back to extract_text."""
    try:
        data = page.get_contents().get_data()
    except Exception:
        data = b""
    chunks = [s for m in _ACTUAL_TEXT.finditer(data) if (s := _decode_hex(m.group(1)))]
    if chunks:
        return "\n\n".join(chunks)
    # Fallback for pages without our spans.
    try:
        return page.extract_text() or ""
    except Exception:
        return ""


def extract(pdf_path: str, page_marker: bool = True) -> str:
    reader = PdfReader(pdf_path)
    parts: list[str] = []
    for i, page in enumerate(reader.pages, 1):
        text = page_text(page).strip()
        if page_marker:
            parts.append(f"===== PAGE {i} =====\n{text}")
        elif text:
            parts.append(text)
    return "\n\n".join(parts).strip() + "\n"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("input", help="An OCR'd PDF (ideally produced by run_tesseract.py)")
    p.add_argument(
        "output",
        nargs="?",
        help="Output .txt path. Default: input name with .txt. Use '-' for stdout.",
    )
    p.add_argument(
        "--no-page-markers",
        action="store_true",
        help="Omit the '===== PAGE N =====' separators (one flowing text).",
    )
    args = p.parse_args()

    text = extract(args.input, page_marker=not args.no_page_markers)

    if args.output == "-":
        sys.stdout.write(text)
        return 0
    out = args.output or (os.path.splitext(args.input)[0] + ".txt")
    with open(out, "w", encoding="utf-8") as handle:
        handle.write(text)
    print(f"Wrote {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
