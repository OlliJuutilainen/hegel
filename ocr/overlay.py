"""Build an invisible, selectable text layer and merge it onto the original page.

For the Tesseract routes the layer is positioned per OCR line and wrapped, per
paragraph, in an /ActualText marked-content span so copy/paste yields clean flowing
paragraph text (de-hyphenated, line breaks collapsed to spaces). For the Claude-vision
route (no coordinates) the text simply flows top-to-bottom, auto-shrunk to fit.
"""

from __future__ import annotations

import dataclasses
import io
import os

from pypdf import PageObject, PdfReader
from reportlab.lib.utils import ImageReader, simpleSplit
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


def _emit_line(c, line_words, scale_x, scale_y, page_h, font):
    """Emit one positioned invisible text block for an entire OCR line.

    Joining a line's words into a single space-separated Tj string gives reliable
    word separation regardless of a reader's gap-inference heuristic. The trailing
    space helps the fallback copy path when /ActualText is not honored.
    """
    if not line_words:
        return
    text = " ".join(w.text for w in line_words if w.text)
    if font == _FALLBACK_FONT:
        text = text.encode("latin-1", "replace").decode("latin-1")
    if not text.strip():
        return

    line_left = min(w.left for w in line_words)
    line_right = max(w.left + w.width for w in line_words)
    line_top = min(w.top for w in line_words)
    line_bottom = max(w.top + w.height for w in line_words)

    size = max((line_bottom - line_top) * scale_y, 1.0)
    x = line_left * scale_x
    y = page_h - line_bottom * scale_y  # baseline at the bottom of the line's bbox

    natural = pdfmetrics.stringWidth(text, font, size)
    target = (line_right - line_left) * scale_x

    text_obj = c.beginText(x, y)
    text_obj.setFont(font, size)
    text_obj.setTextRenderMode(_INVISIBLE)
    if natural > 0 and target > 0:
        text_obj.setHorizScale(100.0 * target / natural)
    text_obj.textLine(text + " ")
    c.drawText(text_obj)


def _group_by_paragraph(words):
    """Group Tesseract words into paragraphs, each an ordered list of lines.

    Returns a list of paragraphs in reading order; each paragraph is a list of lines,
    each line a list of Words sorted left-to-right. Grouping keys come straight from
    Tesseract's layout analysis (block_num, par_num, line_num).
    """
    paras: dict = {}
    for w in words:
        pkey = (getattr(w, "block_num", 0), getattr(w, "par_num", 0))
        paras.setdefault(pkey, []).append(w)

    result = []
    for pkey in sorted(paras.keys()):
        lines: dict = {}
        for w in paras[pkey]:
            lines.setdefault(getattr(w, "line_num", 0), []).append(w)
        ordered = [
            sorted(lines[lk], key=lambda w: (getattr(w, "word_num", 0), w.left))
            for lk in sorted(lines.keys())
        ]
        result.append(ordered)
    return result


def _paragraph_actualtext(lines) -> str:
    """Build the clean copy-text for a paragraph: lines joined, soft hyphens removed.

    A trailing '-' at a line end is treated as a soft (line-break) hyphen and dropped
    when the next line begins with a lowercase letter — this fixes the common case
    ("be-\\ning" -> "being") while leaving most real compound hyphens intact (a capital
    continuation keeps the hyphen). It can still occasionally over-join a genuine
    compound that wraps at its hyphen; a wordlist could refine this later.
    """
    line_texts = []
    for ln in lines:
        t = " ".join(w.text for w in ln if w.text).strip()
        if t:
            line_texts.append(t)

    out = ""
    for i, t in enumerate(line_texts):
        if i == 0:
            out = t
            continue
        if (
            out.endswith("-")
            and len(out) >= 2
            and out[-2].isalpha()
            and t[:1].isalpha()
            and t[:1].islower()
        ):
            out = out[:-1] + t  # de-hyphenate: join directly, no space
        else:
            out = out + " " + t
    return out


def _actualtext_hex(s: str) -> str:
    """Encode a string as a UTF-16BE PDF hex string body with BOM, for /ActualText."""
    return "FEFF" + s.encode("utf-16-be").hex().upper()


def _dehyphenate_lines(lines):
    """Return a copy of `lines` with soft line-break hyphens absorbed.

    When line N's last word ends with '-' (preceded by an alpha char) and line N+1's
    first word starts with a lowercase alpha char, merge them: line N's last word
    becomes 'prefix + nextword' (no hyphen), and line N+1's first word is dropped.

    This rewrites the actual Tj text emitted to the page, so the fix survives readers
    that ignore /ActualText (notably Big Sur Preview). Visible glyphs in the scan are
    untouched — only the invisible OCR layer changes. Caveat: a real compound that
    wraps at its hyphen with a lowercase continuation (e.g. 'self-' / 'assertion')
    gets over-joined. Most academic cases follow soft-hyphen patterns, so net win.
    """
    new = [list(line) for line in lines]
    for i in range(len(new) - 1):
        cur, nxt = new[i], new[i + 1]
        if not cur or not nxt:
            continue
        last = cur[-1]
        first = nxt[0]
        if (
            last.text.endswith("-")
            and len(last.text) >= 2
            and last.text[-2].isalpha()
            and first.text[:1].isalpha()
            and first.text[:1].islower()
        ):
            cur[-1] = dataclasses.replace(last, text=last.text[:-1] + first.text)
            del nxt[0]
    return new


def _emit_paragraph(c, lines, scale_x, scale_y, page_h, font):
    """Emit one paragraph: its positioned per-line text wrapped in an /ActualText span.

    Soft line-break hyphens are absorbed into the previous line's last word first, so
    even readers that ignore /ActualText (Big Sur Preview) yield 'being' instead of
    'be- ing'. The /ActualText span carries the same clean paragraph string for
    spec-conformant readers.
    """
    if not lines:
        return
    lines = _dehyphenate_lines(lines)
    clean = _paragraph_actualtext(lines)
    if font == _FALLBACK_FONT:
        clean = clean.encode("latin-1", "replace").decode("latin-1")

    has_span = bool(clean.strip())
    if has_span:
        c._code.append("/Span << /ActualText <%s> >> BDC" % _actualtext_hex(clean))
    for line_words in lines:
        _emit_line(c, line_words, scale_x, scale_y, page_h, font)
    if has_span:
        c._code.append("EMC")


def build_positioned_overlay_page(
    words,
    img_w: int,
    img_h: int,
    page_w: float,
    page_h: float,
    *,
    font: str = _FALLBACK_FONT,
) -> PageObject:
    """Place each OCR paragraph as positioned invisible text wrapped in an /ActualText span."""
    scale_x = page_w / img_w
    scale_y = page_h / img_h

    packet = io.BytesIO()
    c = canvas.Canvas(packet, pagesize=(page_w, page_h))
    for para in _group_by_paragraph(words):
        _emit_paragraph(c, para, scale_x, scale_y, page_h, font)
    c.showPage()
    c.save()
    packet.seek(0)
    return PdfReader(packet).pages[0]


def build_image_page_with_text(
    image,
    words,
    page_w: float,
    page_h: float,
    *,
    font: str = _FALLBACK_FONT,
    jpeg_quality: int = 85,
) -> PageObject:
    """Build a self-contained PDF page from scratch: the rendered scan as background plus our
    invisible OCR text on top. Any pre-existing (corrupt) text layer in the source PDF is
    dropped, so text selection picks up only the clean OCR layer.
    """
    img_w, img_h = image.size
    scale_x = page_w / img_w
    scale_y = page_h / img_h

    img_buf = io.BytesIO()
    if image.mode != "RGB":
        image = image.convert("RGB")
    image.save(img_buf, format="JPEG", quality=jpeg_quality, optimize=True)
    img_buf.seek(0)

    packet = io.BytesIO()
    c = canvas.Canvas(packet, pagesize=(page_w, page_h))
    c.drawImage(ImageReader(img_buf), 0, 0, width=page_w, height=page_h)
    for para in _group_by_paragraph(words):
        _emit_paragraph(c, para, scale_x, scale_y, page_h, font)

    c.showPage()
    c.save()
    packet.seek(0)
    return PdfReader(packet).pages[0]


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
