"""Build the invisible, selectable text layer that sits over the rendered scan.

The whole paragraph emits as one BT...ET block: per-line positioning via Tm inside
that block plus a /Span /ActualText wrapper, so readers see one cohesive text object
and copy yields clean flowing paragraph text (de-hyphenated, line breaks collapsed).
"""

from __future__ import annotations

import dataclasses
import io
import os
import re

from pypdf import PageObject, PdfReader
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

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


def _emit_line_in(text_obj, line_words, scale_x, scale_y, page_h, font, force_left=None):
    """Emit one OCR line as Tm/Tf/Tz/Tj operators inside an existing PDF text object.

    The whole paragraph shares one BT...ET block (the caller's text object), so the
    reader sees one cohesive text object instead of N separately-positioned ones —
    geometry-based readers like macOS Preview can't then insert paragraph breaks
    "between objects" because there's only one. This matches what OCRmyPDF produces.

    Joining a line's words into a single space-separated Tj gives reliable word
    separation regardless of any gap-inference heuristic. `force_left` (image px)
    overrides the line's left origin so an indented first line or a de-hyphenated
    continuation line still anchors at the paragraph's flush-left margin.
    """
    if not line_words:
        return
    text = _normalize_text(" ".join(w.text for w in line_words if w.text))
    if font == _FALLBACK_FONT:
        text = text.encode("latin-1", "replace").decode("latin-1")
    if not text.strip():
        return

    line_left = min(w.left for w in line_words)
    line_right = max(w.left + w.width for w in line_words)
    line_top = min(w.top for w in line_words)
    line_bottom = max(w.top + w.height for w in line_words)

    left_px = force_left if force_left is not None else line_left
    size = max((line_bottom - line_top) * scale_y, 1.0)
    x = left_px * scale_x
    y = page_h - line_bottom * scale_y

    natural = pdfmetrics.stringWidth(text, font, size)
    target = (line_right - left_px) * scale_x

    text_obj.setTextOrigin(x, y)  # absolute Tm reposition within the same BT block
    text_obj.setFont(font, size)
    text_obj.setHorizScale(100.0 * target / natural if natural > 0 and target > 0 else 100.0)
    text_obj.textOut(text + " ")  # Tj without the line-break T* — stay in this BT


def _group_by_paragraph(words, drop_running_heads: bool = False):
    """Group Tesseract words into paragraphs, each an ordered list of lines.

    Returns a list of paragraphs in reading order; each paragraph is a list of lines,
    each line a list of Words sorted left-to-right. Grouping keys come straight from
    Tesseract's layout analysis (block_num, par_num, line_num).

    Book-page cleanup on the way: footnote reference markers are stripped from the
    body text, the running head is never merged into the first paragraph (and is
    dropped altogether with `drop_running_heads`), and footnotes are kept apart from
    the body and from each other.
    """
    words = _strip_footnote_markers(words)
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
    result = _merge_continuation_paragraphs(result)
    if drop_running_heads and result and _is_running_head(result[0]):
        result = result[1:]
    return _split_footnote_paragraphs(result, _body_height(words))


def _median_height(words) -> float:
    heights = sorted(w.height for w in words)
    return heights[len(heights) // 2] if heights else 0


def _body_height(words) -> float:
    """Median word height of the body text, taken from the upper 60% of the page's
    text so that a long run of footnotes at the bottom can't pass for the body."""
    if not words:
        return 0
    top = min(w.top for w in words)
    bottom = max(w.top + w.height for w in words)
    cutoff = top + 0.6 * (bottom - top)
    return _median_height([w for w in words if w.top <= cutoff] or words)


# A footnote reference that Tesseract emits as a word of its own, e.g. '1', '*', '²'.
_MARKER_WORD = re.compile(r"^[0-9*†‡¹²³⁴⁵⁶⁷⁸⁹⁰]{1,3}$")
# A marker glued onto the preceding word: 'mediation,1', 'consciousness.*', 'being²'.
# Digits only count after punctuation that follows a real word, so 'B2', '§78',
# 'p.12' and 'vol.2' are left alone.
_GLUED_MARKER = re.compile(
    r"(?<=[A-Za-z]{4})([.,;:!?)\]’”\"']+)(?:\d{1,3})$"
    r"|(?<=[A-Za-z.,;:!?)\]’”\"'])[*†‡]+$"
    r"|[¹²³⁴⁵⁶⁷⁸⁹⁰]+$"
)


def _strip_footnote_markers(words):
    """Remove footnote reference markers from the OCR words.

    Two forms: a stand-alone marker word that sits small and raised above its line's
    baseline, or alone on a line of its own (dropped), and a digit/asterisk Tesseract glued onto the preceding word
    (trimmed). Footnote numbers at the start of the footnotes themselves are full
    size and on the baseline, so they survive. A superscript Tesseract reads as a
    quote mark ('mediation,’') can't be told apart from a real quote and stays.
    """
    lines: dict = {}
    for w in words:
        lines.setdefault((w.block_num, w.par_num, w.line_num), []).append(w)
    page_h = _median_height(words)

    out = []
    for w in words:
        line = lines[(w.block_num, w.par_num, w.line_num)]
        others = [o for o in line if o is not w]
        if _MARKER_WORD.match(w.text):
            if others:
                baseline = sorted(o.top + o.height for o in others)[len(others) // 2]
                line_h = _median_height(others)
                raised = w.top + w.height < baseline - 0.25 * line_h
                if raised and w.height < 0.75 * line_h:
                    continue
            elif w.height < 0.6 * page_h:
                continue  # a marker Tesseract split off into a line of its own
        trimmed = _GLUED_MARKER.sub(lambda m: m.group(1) or "", w.text)
        if trimmed != w.text and trimmed:
            w = dataclasses.replace(w, text=trimmed)
        out.append(w)
    return out


def _is_running_head(paragraph) -> bool:
    """True for a one-line paragraph that looks like a running head: the page's book or
    chapter title in capitals, and/or the page number at either end of the line."""
    if len(paragraph) != 1 or not paragraph[0]:
        return False
    tokens = [w.text for w in paragraph[0]]
    letters = [ch for ch in "".join(tokens) if ch.isalpha()]
    mostly_caps = bool(letters) and sum(ch.isupper() for ch in letters) >= 0.8 * len(letters)
    page_number = any(re.fullmatch(r"\d{1,4}|[ivxlcdm]{1,7}", t) for t in (tokens[0], tokens[-1]))
    return mostly_caps or page_number


def _split_footnote_paragraphs(paragraphs, body_height: float):
    """Start a new paragraph at each numbered footnote.

    Tesseract often reads a run of footnotes as one paragraph. Inside paragraphs set
    smaller than the page's body text, a line that opens with a footnote number
    ('1', '12', '*', '†') begins a new footnote. Body paragraphs are left alone, so a
    sentence that happens to start with a year or a number is never split.
    """
    out = []
    for para in paragraphs:
        words = [w for ln in para for w in ln]
        if not body_height or not words or _median_height(words) >= 0.9 * body_height:
            out.append(para)
            continue
        current: list = []
        for ln in para:
            if current and ln and re.fullmatch(r"\d{1,3}\.?|[*†‡]+", ln[0].text):
                out.append(current)
                current = []
            current.append(ln)
        if current:
            out.append(current)
    return out


def _merge_continuation_paragraphs(paragraphs):
    """Merge adjacent paragraphs that look like a single visual paragraph.

    Tesseract sometimes assigns a fresh par_num (and even a fresh block_num) to
    lines that are visually part of the same paragraph, which then renders as a
    paragraph break in any reader that emits one between separate /ActualText spans.
    Two signals: a small vertical gap (≤ ~line height) AND a near-identical left
    margin (a real paragraph break shows up either as a larger gap, or as an indent
    shift, or both — same margin + line-sized gap = continuous prose).
    """
    if not paragraphs:
        return paragraphs
    merged = [paragraphs[0]]
    for nxt in paragraphs[1:]:
        prev = merged[-1]
        if not prev or not nxt or not prev[-1] or not nxt[0]:
            merged.append(nxt)
            continue
        prev_last_line, next_first_line = prev[-1], nxt[0]
        prev_bottom = max(w.top + w.height for w in prev_last_line)
        next_top = min(w.top for w in next_first_line)
        gap = next_top - prev_bottom
        heights = [w.height for w in prev_last_line + next_first_line]
        median_h = sorted(heights)[len(heights) // 2] if heights else 0
        prev_left = min(w.left for w in prev_last_line)
        next_left = min(w.left for w in next_first_line)
        # A change of type size (body -> footnotes) is a break, however tight the gap.
        prev_size = _median_height([w for ln in prev for w in ln])
        next_size = _median_height([w for ln in nxt for w in ln])
        same_size = min(prev_size, next_size) >= 0.85 * max(prev_size, next_size)
        # The running head sits just above the first line; never fold it into the body.
        after_head = len(merged) == 1 and _is_running_head(prev)
        is_continuous = (
            median_h
            and gap <= 1.2 * median_h
            and abs(prev_left - next_left) <= 0.5 * median_h
            and same_size
            and not after_head
        )
        if is_continuous:
            prev.extend(nxt)
        else:
            merged.append(nxt)
    return merged


def _normalize_text(s: str) -> str:
    """Editorial normalization applied to all emitted text and ActualText strings:
    em dash without surrounding spaces becomes spaced en dash, and runs of whitespace
    collapse to a single space.
    """
    return " ".join(s.replace("—", " – ").split())


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
    return _normalize_text(out)


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
    """Emit one paragraph as a single PDF text object wrapped in an /ActualText span.

    All of the paragraph's lines live inside ONE beginText/drawText pair (one BT...ET
    in the resulting content stream). Per-line positioning happens via setTextOrigin
    (Tm) inside that block, and textOut (Tj without T*) keeps each line as a plain
    text-show operator. Readers — including macOS Preview, which insists on its own
    geometric line/paragraph reconstruction — see one cohesive text object and stop
    trying to interleave paragraph breaks "between" objects.

    Also anchors every line at the paragraph's flush-left margin so a first-line
    indent doesn't read as a new-paragraph signal to any leftover geometry checks.
    """
    if not lines:
        return
    lines = _dehyphenate_lines(lines)
    clean = _paragraph_actualtext(lines)
    if font == _FALLBACK_FONT:
        clean = clean.encode("latin-1", "replace").decode("latin-1")

    non_empty = [ln for ln in lines if ln]
    if not non_empty:
        return
    flush_left = (
        min(min(w.left for w in ln) for ln in non_empty[1:])
        if len(non_empty) >= 2
        else min(w.left for w in non_empty[0])
    )

    has_span = bool(clean.strip())
    if has_span:
        c._code.append("/Span << /ActualText <%s> >> BDC" % _actualtext_hex(clean))
    text_obj = c.beginText()
    text_obj.setTextRenderMode(_INVISIBLE)
    for line_words in lines:
        _emit_line_in(text_obj, line_words, scale_x, scale_y, page_h, font, force_left=flush_left)
    c.drawText(text_obj)
    if has_span:
        c._code.append("EMC")


def build_positioned_overlay_page(
    paragraphs,
    img_w: int,
    img_h: int,
    page_w: float,
    page_h: float,
    *,
    font: str = _FALLBACK_FONT,
) -> PageObject:
    """Place each OCR paragraph (from _group_by_paragraph) as positioned invisible text
    wrapped in an /ActualText span."""
    scale_x = page_w / img_w
    scale_y = page_h / img_h

    packet = io.BytesIO()
    c = canvas.Canvas(packet, pagesize=(page_w, page_h))
    for para in paragraphs:
        _emit_paragraph(c, para, scale_x, scale_y, page_h, font)
    c.showPage()
    c.save()
    packet.seek(0)
    return PdfReader(packet).pages[0]


def build_image_page_with_text(
    image,
    paragraphs,
    page_w: float,
    page_h: float,
    *,
    font: str = _FALLBACK_FONT,
    jpeg_quality: int = 85,
) -> PageObject:
    """Build a self-contained PDF page from scratch: the rendered scan as background plus our
    invisible OCR text (paragraphs from _group_by_paragraph) on top. Any pre-existing
    (corrupt) text layer in the source PDF is dropped, so text selection picks up only the
    clean OCR layer.
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
    for para in paragraphs:
        _emit_paragraph(c, para, scale_x, scale_y, page_h, font)

    c.showPage()
    c.save()
    packet.seek(0)
    return PdfReader(packet).pages[0]


