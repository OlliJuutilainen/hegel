#!/usr/bin/env python3
"""Insert a single image as a new page into an existing PDF, preserving annotations.

Use case: a scan (e.g. from CamScanner) is missing one page, which you have as a
photo. Re-scanning the whole book would scramble your existing highlights and
notes. Annotations are page-level (/Annots lives on each page object), so
inserting a page leaves every other page's annotations exactly where they are —
only the page numbering after the insertion point shifts, which is what you want.

The inserted page is sized to match its neighbour (the page it pushes down, or
the last page when appending) and the photo is scaled to fit inside, centred,
on a white background — no existing content is touched or cropped. Phone-photo
EXIF rotation is auto-applied so the page lands upright.

Usage:
    # make the photo become page 53; old page 53 onward shift down by one
    python insert_page.py book.pdf missing.jpg book_fixed.pdf --at 53
"""

from __future__ import annotations

import argparse
import io
import sys

from pypdf import PdfReader, PdfWriter
from PIL import Image, ImageOps
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas


def _build_image_page(image_path: str, width: float, height: float) -> PdfReader:
    """Render the photo onto a single PDF page of the given size (points)."""
    img = Image.open(image_path)
    img = ImageOps.exif_transpose(img)  # honour phone-photo orientation
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")

    iw, ih = img.size
    # Contain: scale to fit inside the page, preserving aspect ratio, centred.
    scale = min(width / iw, height / ih)
    dw, dh = iw * scale, ih * scale
    x = (width - dw) / 2
    y = (height - dh) / 2

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(width, height))
    c.setFillColorRGB(1, 1, 1)
    c.rect(0, 0, width, height, fill=1, stroke=0)
    c.drawImage(ImageReader(img), x, y, width=dw, height=dh)
    c.showPage()
    c.save()
    buf.seek(0)
    return PdfReader(buf)


def insert(input_path: str, image_path: str, output_path: str, at: int) -> int:
    reader = PdfReader(input_path)
    n = len(reader.pages)
    # `at` is the 1-based page number the photo should BECOME; clamp to [1, n+1].
    at = max(1, min(at, n + 1))
    insert_index = at - 1  # 0-based position in the page list

    # Size the new page to match the page it displaces (or the last page if
    # we're appending past the end).
    ref = reader.pages[insert_index] if insert_index < n else reader.pages[-1]
    width = float(ref.mediabox.width)
    height = float(ref.mediabox.height)

    image_page = _build_image_page(image_path, width, height).pages[0]

    writer = PdfWriter()
    for i, page in enumerate(reader.pages):
        if i == insert_index:
            writer.add_page(image_page)
        writer.add_page(page)
    if insert_index == n:  # appending at the very end
        writer.add_page(image_page)

    with open(output_path, "wb") as handle:
        writer.write(handle)

    annot_pages = sum(1 for p in reader.pages if "/Annots" in p)
    print(
        f"Inserted photo as page {at} of {n + 1} -> {output_path} "
        f"(annotations on {annot_pages} page(s) preserved)."
    )
    if ref.get("/Rotate"):
        print(
            f"NOTE: the neighbouring page has /Rotate {ref['/Rotate']}; if the "
            f"inserted page looks sideways, rotate the photo before inserting.",
            file=sys.stderr,
        )
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("input", help="Existing PDF (with your annotations)")
    p.add_argument("image", help="Photo of the missing page (jpg/png)")
    p.add_argument("output", help="Output PDF with the page inserted")
    p.add_argument(
        "--at",
        type=int,
        required=True,
        help="1-based page number the photo should become; existing pages from "
        "there on shift down by one. Use (last page + 1) to append at the end.",
    )
    args = p.parse_args()
    return insert(args.input, args.image, args.output, args.at)


if __name__ == "__main__":
    sys.exit(main())
