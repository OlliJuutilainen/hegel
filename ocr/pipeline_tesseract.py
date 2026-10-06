"""Tesseract OCR of a scanned PDF, written back as an invisible, word-aligned text layer."""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass

from pypdf import PdfReader, PdfWriter
from tqdm import tqdm

from . import render
from .overlay import (
    _dehyphenate_lines,
    _group_by_paragraph,
    _paragraph_actualtext,
    build_image_page_with_text,
    build_positioned_overlay_page,
    get_text_font,
)
from .preprocess import Region, prepare_scan
from .tesseract_ocr import ocr_words


@dataclass
class Settings:
    lang: str = "eng"
    dpi: int = 300  # Tesseract's accuracy sweet spot
    min_conf: float = 0.0
    font_file: str | None = None
    # Rebuild each output page from scratch (image + clean OCR text) so any pre-existing
    # corrupt text layer in the source PDF is dropped. Set False to merge onto the original
    # page instead, which preserves source bytes but keeps the corrupt layer alongside ours.
    rasterize: bool = True
    jpeg_quality: int = 85
    # Leave the running head (book/chapter title + page number) out of the text layer.
    drop_running_heads: bool = False
    # Before OCR, split two-page spreads, clear copier shadows and straighten tilted
    # pages (ocr.preprocess). The output pages keep their original images either way.
    cleanup: bool = True
    # Write the two book pages of a spread as pages of their own, straightened.
    split_spreads: bool = False


def _regions(image, settings: Settings) -> list[Region]:
    if settings.cleanup:
        return prepare_scan(image, settings.dpi)
    return [Region(image, image, 0, 0.0)]


def _on_source(word, region: Region):
    """A word read from a prepared region, placed back on the page's own image."""
    if not region.angle and not region.x0:
        return word
    cx, cy = region.to_source(word.left + word.width / 2, word.top + word.height / 2)
    return dataclasses.replace(
        word, left=round(cx - word.width / 2), top=round(cy - word.height / 2)
    )


def run(
    input_pdf: str,
    output_pdf: str,
    settings: Settings,
    text_sidecar: str | None = None,
) -> list[tuple[int, str]]:
    """OCR every page locally and write a PDF with a word-aligned invisible text layer."""
    total = render.page_count(input_pdf)
    font = get_text_font(settings.font_file)

    reader = PdfReader(input_pdf)
    writer = PdfWriter()
    failures: list[tuple[int, str]] = []
    sidecar_parts: list[str] = []

    for page_no in tqdm(range(1, total + 1), desc="Tesseract", unit="page"):
        page = reader.pages[page_no - 1]
        if page.rotation:
            # The render is upright; make the page so too, or the image is squeezed
            # into the unrotated box (a landscape spread onto a portrait sheet).
            page.transfer_rotation_to_content()
        page_w = float(page.mediabox.width)
        page_h = float(page.mediabox.height)

        image = None
        read: list[tuple[Region, list]] = []  # each book page on the sheet, with its words
        try:
            image = render.render_page(input_pdf, page_no, settings.dpi)
            for region in _regions(image, settings):
                words = ocr_words(region.image, lang=settings.lang, min_conf=settings.min_conf)
                read.append((region, words))
        except Exception as exc:  # one bad page must not abort the whole run
            failures.append((page_no, repr(exc)))
            read = []

        split = settings.split_spreads and len(read) > 1
        drop = settings.drop_running_heads
        # Paragraphs per book page, so a spread's two running heads, footnotes and
        # paragraphs never run into each other.
        per_region = [
            _group_by_paragraph(words if split else [_on_source(w, r) for w in words], drop)
            for r, words in read
        ] or [[]]

        if split:
            for (region, _), paragraphs in zip(read, per_region):
                width = page_w * region.plain.size[0] / image.size[0]
                writer.add_page(build_image_page_with_text(
                    region.plain, paragraphs, width, page_h,
                    font=font, jpeg_quality=settings.jpeg_quality,
                ))
        else:
            paragraphs = [p for ps in per_region for p in ps]
            if settings.rasterize and image is not None:
                # Rebuild from scratch — drops any pre-existing text layer entirely.
                writer.add_page(build_image_page_with_text(
                    image, paragraphs, page_w, page_h,
                    font=font, jpeg_quality=settings.jpeg_quality,
                ))
            elif paragraphs and image is not None:
                # Merge onto the original page (keeps pre-existing text alongside ours).
                overlay = build_positioned_overlay_page(
                    paragraphs, image.size[0], image.size[1], page_w, page_h, font=font,
                )
                page.merge_page(overlay)
                writer.add_page(page)
            else:
                writer.add_page(page)

        if text_sidecar is not None:
            for k, paragraphs in enumerate(per_region):
                label = f"{page_no}{'ab'[k]}" if len(per_region) > 1 else str(page_no)
                sidecar_parts.append(
                    f"\n\n===== PAGE {label} =====\n"
                    + "\n\n".join(_paragraph_actualtext(_dehyphenate_lines(p))
                                  for p in paragraphs)
                )

    with open(output_pdf, "wb") as handle:
        writer.write(handle)

    if text_sidecar is not None:
        with open(text_sidecar, "w", encoding="utf-8") as handle:
            handle.write("".join(sidecar_parts).lstrip())

    return failures
