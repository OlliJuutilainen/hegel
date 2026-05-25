"""Render PDF pages to images via pdf2image (requires the Poppler system binaries)."""

from __future__ import annotations

from pdf2image import convert_from_path, pdfinfo_from_path
from PIL.Image import Image


def page_count(pdf_path: str) -> int:
    return int(pdfinfo_from_path(pdf_path)["Pages"])


def render_page(pdf_path: str, page_number: int, dpi: int) -> Image:
    """Render a single 1-based page to a PIL image, one page at a time to keep memory flat."""
    images = convert_from_path(
        pdf_path, dpi=dpi, first_page=page_number, last_page=page_number
    )
    return images[0]
