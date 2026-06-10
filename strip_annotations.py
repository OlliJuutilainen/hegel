#!/usr/bin/env python3
"""Strip annotations (highlights, ink notes, etc.) from a PDF, keeping the page content.

Why: when you OCR a PDF that has e-ink handwriting or highlights drawn on it, the
renderer paints those marks onto the page image that Tesseract reads — so the ink
contaminates text recognition. Strip the annotations first, OCR the clean copy, then
put the annotations back with migrate_annotations.py.

The annotations are not destroyed: they still live in your original PDF, and
migrate_annotations.py copies them onto the OCR'd output afterwards.

Full workflow:
    python strip_annotations.py marked.pdf clean.pdf
    python run_tesseract.py clean.pdf clean_OCR.pdf
    python migrate_annotations.py marked.pdf clean_OCR.pdf final.pdf

Usage:
    python strip_annotations.py marked.pdf clean.pdf
"""

from __future__ import annotations

import argparse
import sys

from pypdf import PdfReader, PdfWriter
from pypdf.generic import NameObject


def strip(input_path: str, output_path: str) -> int:
    reader = PdfReader(input_path)
    writer = PdfWriter()

    stripped_pages = 0
    stripped_total = 0
    for page in reader.pages:
        if "/Annots" in page:
            stripped_total += len(page["/Annots"])
            stripped_pages += 1
            del page[NameObject("/Annots")]
        writer.add_page(page)

    with open(output_path, "wb") as handle:
        writer.write(handle)

    print(
        f"Stripped {stripped_total} annotation(s) from {stripped_pages} page(s); "
        f"clean copy -> {output_path}"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", help="PDF with annotations to remove")
    parser.add_argument("output", help="Output PDF without annotations")
    args = parser.parse_args()
    return strip(args.input, args.output)


if __name__ == "__main__":
    sys.exit(main())
