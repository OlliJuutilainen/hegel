"""Route 2 pipeline: local Tesseract OCR with a properly positioned invisible layer."""

from __future__ import annotations

from dataclasses import dataclass

from pypdf import PdfReader, PdfWriter
from tqdm import tqdm

from . import render
from .overlay import (
    build_image_page_with_text,
    build_positioned_overlay_page,
    get_text_font,
)
from .tesseract_ocr import is_margin_ref, ocr_words


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
    # Drop Akademie-Ausgabe-style margin references ([4:408]) from the text layer so
    # they don't get copied along with selected body text. The page image is unaffected.
    drop_margin_refs: bool = False


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
        page_w = float(page.mediabox.width)
        page_h = float(page.mediabox.height)

        words = []
        image = None
        try:
            image = render.render_page(input_pdf, page_no, settings.dpi)
            words = ocr_words(image, lang=settings.lang, min_conf=settings.min_conf)
            if settings.drop_margin_refs:
                words = [w for w in words if not is_margin_ref(w.text)]
        except Exception as exc:  # one bad page must not abort the whole run
            failures.append((page_no, repr(exc)))

        if settings.rasterize and image is not None:
            # Rebuild from scratch — drops any pre-existing text layer entirely.
            new_page = build_image_page_with_text(
                image, words, page_w, page_h, font=font, jpeg_quality=settings.jpeg_quality
            )
            writer.add_page(new_page)
        elif words and image is not None:
            # Legacy: merge onto the original page (keeps pre-existing text alongside ours).
            overlay = build_positioned_overlay_page(
                words, image.size[0], image.size[1], page_w, page_h, font=font
            )
            page.merge_page(overlay)
            writer.add_page(page)
        else:
            writer.add_page(page)

        if text_sidecar is not None:
            sidecar_parts.append(
                f"\n\n===== PAGE {page_no} =====\n" + " ".join(w.text for w in words)
            )

    with open(output_pdf, "wb") as handle:
        writer.write(handle)

    if text_sidecar is not None:
        with open(text_sidecar, "w", encoding="utf-8") as handle:
            handle.write("".join(sidecar_parts).lstrip())

    return failures
