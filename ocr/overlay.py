"""Build an invisible, selectable text layer and merge it onto the original page.

Claude returns text but no coordinates, so the layer cannot be pixel-aligned to the
scan. Instead the text flows top-to-bottom in reading order and is auto-shrunk so the
whole transcription fits within the page bounds, keeping it searchable and copyable.
"""

from __future__ import annotations

import io
import os

from pypdf import PageObject, PdfReader
from reportlab.lib.utils import simpleSplit
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

_MARGIN = 40
_FALLBACK_FONT = "Helvetica"
_INVISIBLE = 3  # PDF text render mode: neither fill nor stroke

# Best-effort Unicode font so Greek (and other non-Latin) text stays in the layer.
_UNICODE_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
    "/Library/Fonts/Arial Unicode.ttf",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "C:\\Windows\\Fonts\\arial.ttf",
]

_registered_font: str | None = None


def get_text_font(font_file: str | None = None) -> str:
    """Register and return a Unicode TTF if one is available, else fall back to Helvetica."""
    global _registered_font
    if _registered_font is not None:
        return _registered_font
    for path in [font_file, *_UNICODE_FONT_CANDIDATES]:
        if path and os.path.exists(path):
            try:
                pdfmetrics.registerFont(TTFont("OCRUnicode", path))
                _registered_font = "OCRUnicode"
                return _registered_font
            except Exception:
                continue
    _registered_font = _FALLBACK_FONT
    return _registered_font


def _line_count(text: str, font: str, size: float, usable_w: float) -> int:
    total = 0
    for paragraph in text.split("\n"):
        total += len(simpleSplit(paragraph, font, size, usable_w) or [""])
    return total


def _fit_font_size(
    text: str,
    usable_w: float,
    usable_h: float,
    font: str,
    max_font: float,
    min_font: float,
    leading_ratio: float,
) -> float:
    size = max_font
    while size > min_font:
        if _line_count(text, font, size, usable_w) * size * leading_ratio <= usable_h:
            return size
        size -= 0.5
    return min_font


def build_overlay_page(
    text: str,
    width: float,
    height: float,
    *,
    font: str = _FALLBACK_FONT,
    max_font: float = 11.0,
    min_font: float = 4.0,
    leading_ratio: float = 1.2,
    margin: float = _MARGIN,
) -> PageObject:
    # Helvetica is Latin-1 only; sanitize so non-Latin glyphs can't crash the layout.
    if font == _FALLBACK_FONT:
        text = text.encode("latin-1", "replace").decode("latin-1")

    packet = io.BytesIO()
    c = canvas.Canvas(packet, pagesize=(width, height))
    if text.strip():
        usable_w = width - 2 * margin
        usable_h = height - 2 * margin
        size = _fit_font_size(
            text, usable_w, usable_h, font, max_font, min_font, leading_ratio
        )
        text_obj = c.beginText(margin, height - margin - size)
        text_obj.setFont(font, size)
        text_obj.setTextRenderMode(_INVISIBLE)
        text_obj.setLeading(size * leading_ratio)
        for paragraph in text.split("\n"):
            for line in simpleSplit(paragraph, font, size, usable_w) or [""]:
                text_obj.textLine(line)
        c.drawText(text_obj)
    c.showPage()  # finalize exactly one page, even when the text is blank
    c.save()
    packet.seek(0)
    return PdfReader(packet).pages[0]
