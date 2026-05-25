"""Route 2 pipeline: local Tesseract OCR with a properly positioned invisible layer."""

from __future__ import annotations

from dataclasses import dataclass

from pypdf import PdfReader, PdfWriter
from tqdm import tqdm

from . import render
from .overlay import build_positioned_overlay_page, get_text_font
from .tesseract_ocr import ocr_words


@dataclass
class Settings:
    lang: str = "eng"
    dpi: int = 300  # Tesseract's accuracy sweet spot
    min_conf: float = 0.0
    font_file: str | None = None


def run(
    input_pdf: str,
    output_pdf: str,
    settings: Settings,
    text_sidecar: str | None = None,
) -> list[tuple[int, str]]:
    """OCR every page locally and bake a word-aligned invisible layer onto the originals."""
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
        try:
            image = render.render_page(input_pdf, page_no, settings.dpi)
            words = ocr_words(image, lang=settings.lang, min_conf=settings.min_conf)
            img_w, img_h = image.size
        except Exception as exc:  # one bad page must not abort the whole run
            failures.append((page_no, repr(exc)))
            img_w = img_h = 0

        if words and img_w and img_h:
            overlay = build_positioned_overlay_page(
                words, img_w, img_h, page_w, page_h, font=font
            )
            page.merge_page(overlay)
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
