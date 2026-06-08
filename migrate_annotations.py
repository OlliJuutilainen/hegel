#!/usr/bin/env python3
"""Migrate PDF annotations (highlights, underlines, notes, etc.) from one PDF to another.

Use case: you have an older copy of a scanned book that you've highlighted in Preview;
that copy has no text layer (or a corrupt one). The new OCR'd copy has clean text but
no highlights. This script lifts the annotations from the old PDF onto the new one,
producing a third PDF with both: the OCR layer and your existing highlights.

The page count and per-page dimensions must match between the two PDFs — both should
come from the same source scan. The script warns if they don't.

Usage:
    python migrate_annotations.py vanha.pdf uusi_OCR.pdf yhdistetty.pdf
"""

from __future__ import annotations

import argparse
import sys

from pypdf import PdfReader, PdfWriter
from pypdf.generic import NameObject


def migrate(old_path: str, new_path: str, output_path: str) -> int:
    old = PdfReader(old_path)
    new = PdfReader(new_path)

    if len(old.pages) != len(new.pages):
        print(
            f"WARNING: page count mismatch ({len(old.pages)} in {old_path}, "
            f"{len(new.pages)} in {new_path}). Migrating annotations only for the "
            f"overlapping range.",
            file=sys.stderr,
        )

    writer = PdfWriter()
    total = 0
    pages_with_annots = 0
    for i, new_page in enumerate(new.pages):
        if i < len(old.pages):
            old_page = old.pages[i]
            # Page-dimension sanity check
            if (
                float(old_page.mediabox.width) != float(new_page.mediabox.width)
                or float(old_page.mediabox.height) != float(new_page.mediabox.height)
            ):
                print(
                    f"WARNING: page {i + 1} dimensions differ "
                    f"(old {old_page.mediabox.width}x{old_page.mediabox.height} vs "
                    f"new {new_page.mediabox.width}x{new_page.mediabox.height}). "
                    f"Annotations may appear in the wrong place on this page.",
                    file=sys.stderr,
                )
            if "/Annots" in old_page:
                new_page[NameObject("/Annots")] = old_page["/Annots"]
                total += len(old_page["/Annots"])
                pages_with_annots += 1
        writer.add_page(new_page)

    with open(output_path, "wb") as handle:
        writer.write(handle)

    print(
        f"Migrated {total} annotation(s) from {pages_with_annots} page(s) "
        f"of {old_path} -> {output_path}"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("old", help="Old PDF that has the existing highlights/annotations")
    parser.add_argument("new", help="New PDF (e.g. the OCR'd version) that lacks them")
    parser.add_argument("output", help="Output PDF combining the new content + old annotations")
    args = parser.parse_args()
    return migrate(args.old, args.new, args.output)


if __name__ == "__main__":
    sys.exit(main())
